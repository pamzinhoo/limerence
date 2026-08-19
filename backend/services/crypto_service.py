"""
crypto_service.py
==================

Responsavel pela criptografia/descriptografia dos pacotes de DLC.

POR QUE ISSO EXISTE
--------------------
Um arquivo de DLC .enc que fica no disco do usuario (baixado pelo launcher,
ou ate mesmo distribuido junto do jogo base pela itch.io) NAO PODE conter
conteudo jogavel em texto claro. Se contivesse, bastaria o usuario trocar
uma extensao ou pular uma verificacao no Ren'Py para "destravar" a DLC
localmente, sem nunca falar com o backend.

Usamos AES-256-GCM:
- AES-256: cifra forte, padrao de mercado.
- GCM: modo autenticado -> qualquer bit alterado no arquivo .enc faz a
  descriptografia falhar (protege contra adulteracao do arquivo, nao so
  contra leitura).

A CHAVE NUNCA FICA NO CLIENTE
------------------------------
Cada DLC tem uma chave AES-256 propria, gerada no momento do empacotamento
(package_dlc.py). Essa chave e guardada SOMENTE no backend, dentro da coluna
`encryption_key_encrypted` da tabela dlc (ou tabela propria), e ela mesma
fica criptografada em repouso com uma "master key" que so existe como
variavel de ambiente do servidor (DLC_MASTER_KEY), nunca committada,
nunca em arquivo do jogo/launcher.

Fluxo de uso:
    1. Staff empacota a DLC (package_dlc.py) -> gera dlc_XXX.enc + chave.
    2. Backend guarda a chave (envelope-encrypted com a master key).
    3. Launcher, so depois de autorizacao confirmada, recebe a chave via
       endpoint /launcher/dlc/{slug}/authorize (token de curta duracao).
    4. Launcher/jogo usa a chave em memoria para decifrar, nunca grava a
       chave em disco.
"""

from __future__ import annotations

import os
import base64
import hashlib
from dataclasses import dataclass

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

# Tamanho do nonce recomendado para GCM (96 bits / 12 bytes).
NONCE_SIZE = 12
KEY_SIZE = 32  # AES-256


class CryptoError(Exception):
    """Erro generico de criptografia/descriptografia (chave errada, arquivo
    corrompido, ou adulterado)."""


def generate_dlc_key() -> bytes:
    """Gera uma chave AES-256 aleatoria e unica para uma nova DLC.

    Cada DLC tem SUA PROPRIA chave. Isso significa que vazar/quebrar a
    chave de uma DLC nao compromete as outras (compartimentalizacao).
    """
    return AESGCM.generate_key(bit_length=256)


def encrypt_dlc_package(plaintext_bytes: bytes, key: bytes) -> bytes:
    """Criptografa o conteudo bruto de uma DLC (ex: um .zip do conteudo)
    e retorna o payload final que vira o arquivo .enc.

    Formato do arquivo .enc:
        [12 bytes nonce] + [ciphertext] + [16 bytes tag GCM embutido]

    O nonce NAO e segredo (pode ir junto do arquivo), mas precisa ser
    unico por (chave, mensagem) -- por isso geramos um novo nonce aleatorio
    a cada empacotamento.
    """
    if len(key) != KEY_SIZE:
        raise CryptoError("Chave invalida: esperado AES-256 (32 bytes).")

    nonce = os.urandom(NONCE_SIZE)
    aesgcm = AESGCM(key)
    ciphertext = aesgcm.encrypt(nonce, plaintext_bytes, associated_data=None)
    return nonce + ciphertext


def decrypt_dlc_package(enc_bytes: bytes, key: bytes) -> bytes:
    """Descriptografa um pacote .enc usando a chave fornecida.

    Isso SO deve ser chamado depois que o backend autorizou a liberacao
    da chave para aquele usuario/sessao especifica. A funcao em si nao
    sabe nada sobre autorizacao -- autorizacao acontece antes, no backend
    (ver dlc_license_service.py). Isto e proposital: criptografia e
    autorizacao sao responsabilidades separadas.

    Levanta CryptoError se:
      - a chave estiver errada;
      - o arquivo tiver sido adulterado (tag GCM nao bate);
      - o arquivo estiver corrompido/truncado.
    """
    if len(key) != KEY_SIZE:
        raise CryptoError("Chave invalida: esperado AES-256 (32 bytes).")
    if len(enc_bytes) < NONCE_SIZE + 16:
        raise CryptoError("Arquivo .enc invalido ou truncado.")

    nonce, ciphertext = enc_bytes[:NONCE_SIZE], enc_bytes[NONCE_SIZE:]
    aesgcm = AESGCM(key)
    try:
        return aesgcm.decrypt(nonce, ciphertext, associated_data=None)
    except Exception as exc:  # cryptography levanta InvalidTag
        raise CryptoError(
            "Falha ao descriptografar: chave incorreta ou arquivo adulterado."
        ) from exc


def sha256_hex(data: bytes) -> str:
    """Hash de integridade do arquivo .enc (o mesmo conceito que ja existe
    no GameManifestEntry do backend). Usado para o launcher confirmar que
    baixou o arquivo certo, sem revelar nada sobre o conteudo."""
    return hashlib.sha256(data).hexdigest()


# ---------------------------------------------------------------------------
# Envelope encryption da chave da DLC em repouso (para guardar no banco)
# ---------------------------------------------------------------------------

def _load_master_key() -> bytes:
    """Le a master key do ambiente do SERVIDOR (nunca do cliente).

    Deve ser configurada como variavel de ambiente:
        DLC_MASTER_KEY=<32 bytes em base64>
    Gere uma vez com:
        python -c "import os,base64;print(base64.b64encode(os.urandom(32)).decode())"
    e guarde em um secrets manager / .env do servidor -- NUNCA no repositorio,
    NUNCA no jogo, NUNCA no launcher.
    """
    raw = os.environ.get("DLC_MASTER_KEY")
    if not raw:
        raise RuntimeError(
            "DLC_MASTER_KEY nao configurada no ambiente do backend. "
            "Sem ela o servidor nao consegue abrir as chaves das DLCs."
        )
    key = base64.b64decode(raw)
    if len(key) != KEY_SIZE:
        raise RuntimeError("DLC_MASTER_KEY deve ter 32 bytes (AES-256).")
    return key


def wrap_dlc_key(dlc_key: bytes) -> str:
    """Criptografa a chave de uma DLC especifica com a master key do
    servidor, para poder guardar no banco de dados com seguranca.
    Retorna uma string base64 pronta para salvar em uma coluna TEXT.
    """
    master_key = _load_master_key()
    wrapped = encrypt_dlc_package(dlc_key, master_key)
    return base64.b64encode(wrapped).decode("ascii")


def unwrap_dlc_key(wrapped_b64: str) -> bytes:
    """Reverso de wrap_dlc_key: le a coluna do banco e devolve a chave
    AES-256 real da DLC, pronta para uso em memoria."""
    master_key = _load_master_key()
    wrapped = base64.b64decode(wrapped_b64)
    return decrypt_dlc_package(wrapped, master_key)
