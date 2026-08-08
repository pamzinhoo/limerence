# Sistema de Diário — documentação

Explica o que foi implementado, onde cada peça mora e como reusar/estender.

## Arquivos envolvidos

| Arquivo | O que tem |
|---|---|
| `game/perfil.rpy` | Declaração das imagens, variáveis, função `diario_notificar()`, screen `perfil_janela` (a janela do diário em si) |
| `game/screens.rpy` | Ícone do diário + selo de notificação, dentro da screen `quick_menu` |
| `game/script.rpy` | Ponto do roteiro (label `start`) que chama `diario_notificar()` pela primeira vez |
| `game/images/diariopagina1.png` | Primeira página do diário (a foto que o jogador vê ao abrir) |
| `game/images/diarioselo.png` | Selo "diário atualizado" (aparece abaixo do ícone) |
| `game/audio/lapis.mp3` | Som tocado quando o selo liga |

## Por que os arquivos foram renomeados (e o bug real por trás disso)

Os arquivos originais eram `img_diario_dentro.png` e `diario_atualizado.png`.
Nome de arquivo com `_` pode, em outras situações do Ren'Py, ser interpretado
como "tag + atributos" em vez do nome literal — por precaução, renomeei sem
`_` (`diariopagina1.png`, `diarioselo.png`).

**Mas essa não era a causa real da página não aparecer.** A causa real:
o código usa `renpy.loadable(caminho)` pra checar se a página existe antes
de mostrar. `renpy.loadable()` verifica um **arquivo no disco** (ex:
`"images/diariopagina1.png"`) — ele não sabe nada sobre nomes de
imagem/tag registrados com `image nome = "arquivo.png"`. Eu tinha guardado
em `persistent.diario_paginas` só o nome da tag (`"diariopagina1"`), então
`renpy.loadable("diariopagina1")` sempre retornava `False`, sem erro
nenhum, e o jogo caía no texto de placeholder "Nenhuma página do diário
ainda." mesmo com o arquivo existindo e a imagem certinha.

**Correção:** `persistent.diario_paginas` guarda o **caminho do arquivo**
(`"images/diariopagina1.png"`), não um nome de tag. Não existe mais
`image diariopagina1 = ...` / `image diarioselo = ...` — o `add` usa o
caminho direto (`add "images/diarioselo.png"`), que funciona tanto pra
`add` quanto pra `renpy.loadable()`.

**Regra pra qualquer imagem nova do diário: sempre use o caminho completo
(`"images/arquivo.png"`), nunca só o nome do arquivo sem extensão/pasta.**

## Como funciona

### 1. Selo "diário atualizado" (`persistent.diario_notificacao`)

- Fica abaixo do ícone do diário (canto superior direito), dentro de
  `screens.rpy` → `screen quick_menu` → bloco `fixed:` do diário.
- Tamanho/posição final: `xysize (65, 62)`, `xpos 1868 xanchor 0.5`,
  `ypos 84` (ajustado visualmente até encaixar embaixo do ícone).

**Pegadinha que já mordeu uma vez — cropar ANTES de redimensionar:**
o arquivo `diarioselo.png` (e o `diariopagina1.png`) vinham de uma export
com canvas gigante (5000x2686) e o desenho de verdade ocupando só um
cantinho minúsculo dele (o resto é transparente/branco). Se você só
redimensionar o canvas inteiro pra um tamanho de ícone, o desenho encolhe
junto e vira um pontinho borrado. **Sempre recorte pelo bounding box do
conteúdo primeiro** (remover a moldura transparente em volta), só depois
redimensione. Em Python/Pillow:
  ```python
  from PIL import Image
  im = Image.open("arquivo.png").convert("RGBA")
  im.crop(im.getbbox()).save("arquivo.png")
  ```
- Liga com a função `diario_notificar()` (definida em `perfil.rpy`), que:
  1. Seta `persistent.diario_notificacao = True` (mostra o selo)
  2. Toca `audio/lapis.mp3` (pode desligar passando `diario_notificar(tocar_som=False)`)
- Desliga sozinho quando o jogador clica no ícone do diário (a `action` do
  `imagebutton` já limpa a flag).
- Hoje só é chamada uma vez, em `script.rpy` (label `start`, logo após
  `$ persistent.prota_data = prota_data`). Pra acender de novo em qualquer
  outro ponto do roteiro (nova página, evento importante, etc.):

  ```renpy
  $ diario_notificar()
  ```

### 2. Páginas do diário (`persistent.diario_paginas`)

- Lista de CAMINHOS de imagem, na ordem em que aparecem no diário.
  Hoje: `["images/diariopagina1.png"]`.
- O jogador sempre abre o diário na primeira página (índice
  `diario_pagina_atual = 0`, resetado toda vez que o ícone é clicado).
- Setas `‹` `›` (dentro da screen `perfil_janela`) andam entre as páginas;
  só aparecem quando existe página anterior/próxima.

**Pra adicionar uma página nova:**

1. Coloque o arquivo em `game/images/` (ex: `diariopagina2.png`).
2. Em qualquer ponto do roteiro, adicione o CAMINHO completo na lista:
   ```renpy
   $ persistent.diario_paginas.append("images/diariopagina2.png")
   ```
3. (Opcional) avise o jogador que tem página nova:
   ```renpy
   $ diario_notificar()
   ```

### 3. Encaixe da imagem dentro do livro

A janela do diário (`screen perfil_janela`, em `perfil.rpy`) tem duas camadas:

- **Camada de FORA** — moldura/capa do livro (`Frame("gui/frame.png", ...)`
  + barra "📖 DIÁRIO" no topo). É só borda, nunca deve ser coberta.
- **Camada de DENTRO** — o frame com fundo `#f0e8d8` (a "folha"). É dentro
  dela que a imagem da página deve caber: `xysize (1190, 585)`,
  `fit "contain"`. **Não aumente esse tamanho** — se aumentar, a imagem passa
  por cima da moldura de fora.

## Persistência

`diario_notificacao` e `diario_paginas` são salvos em `persistent` — ou seja,
sobrevivem a fechar/abrir o jogo e são os mesmos em todos os saves (não são
por save, são por instalação do jogo). `diario_pagina_atual` é uma variável
normal de jogo (reseta a cada abertura do diário, não precisa persistir).
