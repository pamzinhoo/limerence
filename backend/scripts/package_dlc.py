"""
package_dlc.py
===============

Ferramenta de STAFF (roda no servidor/maquina de build, nunca no cliente)
para transformar uma pasta de conteudo de DLC pronta em um pacote .enc
distribuivel + registrar a chave no backend.

Uso:
    python package_dlc.py --input ./dlc_source/the_empress \\
                           --output ./dist/dlc_001.enc \\
                           --slug DLC_001

O QUE ISSO FAZ
---------------
1. Zipa a pasta de conteudo da DLC (script .rpy, imagens, audio, etc).
2. Gera uma chave AES-256 nova e unica para essa DLC.
3. Criptografa o zip inteiro com essa chave -> dlc_001.enc.
4. Calcula SHA-256 do .enc (para o manifest/launcher validar integridade
   no download, igual ja existe para o jogo base).
5. Imprime a chave "wrapped" (protegida pela master key do servidor) para
   voce salvar na coluna do banco (product.encryption_key_encrypted).

O .enc resultante pode ser:
  a) hospedado no backend/CDN para o launcher baixar sob demanda (RECOMENDADO
     -- assim quem nunca comprou a DLC nem tem o arquivo no disco); ou
  b) incluido no build distribuido pela itch.io (o pedido original exige que
     o sistema continue seguro MESMO NESSE CASO -- e continua, porque sem a
     chave o arquivo e ilegivel).
"""

from __future__ import annotations

import argparse
import io
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # achar backend/ (raiz do pacote)

from services import crypto_service  # noqa: E402


def zip_folder(folder: Path) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(folder.rglob("*")):
            if path.is_file():
                zf.write(path, arcname=path.relative_to(folder))
    return buf.getvalue()


def main() -> None:
    parser = argparse.ArgumentParser(description="Empacota e criptografa uma DLC do Limerence.")
    parser.add_argument("--input", required=True, help="Pasta com o conteudo pronto da DLC")
    parser.add_argument("--output", required=True, help="Caminho do arquivo .enc de saida")
    parser.add_argument("--slug", required=True, help="Identificador da DLC, ex: DLC_001")
    args = parser.parse_args()

    input_dir = Path(args.input)
    output_path = Path(args.output)
    if not input_dir.is_dir():
        raise SystemExit(f"Pasta de entrada nao encontrada: {input_dir}")

    print(f"[1/4] Compactando conteudo de {input_dir} ...")
    plaintext_zip = zip_folder(input_dir)
    print(f"      -> {len(plaintext_zip)} bytes")

    print("[2/4] Gerando chave AES-256 unica para esta DLC ...")
    dlc_key = crypto_service.generate_dlc_key()

    print("[3/4] Criptografando pacote (AES-256-GCM) ...")
    enc_bytes = crypto_service.encrypt_dlc_package(plaintext_zip, dlc_key)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(enc_bytes)

    digest = crypto_service.sha256_hex(enc_bytes)
    print(f"      -> gravado em {output_path} ({len(enc_bytes)} bytes)")
    print(f"      -> sha256: {digest}")

    print("[4/4] Protegendo a chave para guardar no banco (envelope com DLC_MASTER_KEY) ...")
    try:
        wrapped_key = crypto_service.wrap_dlc_key(dlc_key)
    except RuntimeError as exc:
        print(f"\n[AVISO] Nao consegui empacotar a chave: {exc}")
        print("Configure DLC_MASTER_KEY no ambiente antes de rodar em producao.")
        print("Chave EM TEXTO CLARO (guarde com cuidado, so para teste local):")
        print(f"  {dlc_key.hex()}")
        return

    print("\n>>> Salve isto no backend, associado ao Product/DLC:")
    print(f"    slug               = {args.slug}")
    print(f"    encryption_key_enc = {wrapped_key}")
    print(f"    manifest_sha256    = {digest}")
    print(f"    manifest_size      = {len(enc_bytes)}")
    print("\nDica: chame o endpoint interno de publicacao de manifest do backend")
    print("(o mesmo que ja existe, POST /internal/products/{id}/manifest) para")
    print("registrar isso oficialmente, em vez de editar o banco a mao.")


if __name__ == "__main__":
    main()
