################################################################################
## Janela de Perfil do Personagem
################################################################################

## Imagens do diário: usadas SEMPRE pelo caminho do arquivo (ex:
## "images/diariopagina1.png"), nunca por um nome de imagem/tag registrado
## (ex: "diariopagina1" sozinho). Motivo: o código usa `renpy.loadable(...)`
## pra checar se a página existe antes de mostrar, e `renpy.loadable()`
## verifica um ARQUIVO no disco — não sabe o que é uma tag de imagem
## registrada por `image nome = ...`. Usar só o nome da tag faz
## `renpy.loadable()` sempre retornar False (foi exatamente esse bug: a
## página nunca aparecia, mesmo com o arquivo existindo e a imagem
## declarada). Por isso não há `image diariopagina1 = ...` aqui — é só o
## caminho mesmo, direto.

init -1:

    transform book_entrance:
        alpha 0.0
        yoffset 50
        pause 0.0
        ease 0.5:
            alpha 1.0 
            yoffset 0
       

    transform slide_fade_in:
        alpha 0.0
        xoffset 200
        ease 0.4 alpha 1.0 xoffset 0

    transform fade_bg:
        alpha 0.0
        ease 0.3 alpha 0.6

    transform page_flip_in:
        xtile 0.0
        xzoom 0.1
        alpha 0.3
        ease 0.6 xtile 1.0 xzoom 1.0 alpha 1.0

    transform page_sway:
        rotate 0.0
        linear 1.5 rotate -0.5
        linear 1.5 rotate 0.5
        linear 1.5 rotate 0.0
        repeat


################################################################################
## Selo de "Diário Atualizado"
################################################################################
## O que é: um selo (imagem) que aparece logo ABAIXO do ícone do diário
## (canto superior direito, veja `screens.rpy` -> screen quick_menu) avisando
## o jogador que há uma página nova pra ler. Toca o som de um lápis
## (audio/lapis.mp3) quando aparece.
##
## Arquivos usados:
##   - Imagem do selo: game/images/diarioselo.png
##       (usada pelo caminho direto em screens.rpy: add "images/diarioselo.png")
##   - Som:            game/audio/lapis.mp3
##   - Exibição do selo: screens.rpy, screen quick_menu, logo após o
##     imagebutton do diário.
##
## Como usar (para outros devs):
##   Hoje o selo só é ativado uma vez, logo depois do jogador escolher o
##   gênero da protagonista (ver script.rpy, label start, após
##   `$ persistent.prota_data = prota_data`). Para o diário atualizar de novo
##   em qualquer outro ponto do roteiro (nova página, novo evento, etc.),
##   basta chamar a função abaixo:
##
##       $ diario_notificar()
##
##   O selo some sozinho quando o jogador clica no ícone do diário (o clique
##   já desliga `persistent.diario_notificacao`, ver screens.rpy).
##   Se quiser trocar a imagem do selo, é só sobrescrever
##   game/images/diarioselo.png (ou trocar o caminho usado no `add` dentro de
##   screens.rpy, se o nome do arquivo mudar).

default persistent.diario_notificacao = False

init python:
    def diario_notificar(tocar_som=True):
        """Ativa o selo de diário atualizado e (opcionalmente) toca o som de lápis."""
        persistent.diario_notificacao = True
        if tocar_som:
            renpy.play("audio/lapis.mp3")


################################################################################
## Páginas do Diário
################################################################################
## `persistent.diario_paginas` é a lista de páginas (imagens) do diário, na
## ordem em que devem ser lidas. O jogador abre o diário sempre na primeira
## página (índice 0) e passa pro lado com as setas ‹ › (ver screen
## `perfil_janela` mais abaixo).
##
## Como adicionar uma página nova (para outros devs):
##   1. Coloque a imagem em game/images/ (ex: game/images/diariopagina2.png).
##   2. Adicione o CAMINHO completo no fim da lista, em qualquer ponto do
##      roteiro (não é o nome de uma imagem/tag — é o caminho do arquivo,
##      igual ao usado no exemplo abaixo):
##          $ persistent.diario_paginas.append("images/diariopagina2.png")
##      (Se quiser também avisar o jogador que há algo novo, chame
##      `diario_notificar()` logo em seguida — ver seção acima.)
##
## IMPORTANTE sobre o encaixe da imagem:
##   A janela do diário tem duas camadas (ver screen `perfil_janela`):
##     - camada de FORA: a moldura/capa do livro (background Frame("gui/frame.png", ...)
##       + a barra "📖 DIÁRIO" no topo) — isso é só borda, nunca deve ser coberto.
##     - camada de DENTRO: o frame com fundo "#f0e8d8" (a "folha" do diário) —
##       é DENTRO dela que a imagem da página deve caber (`xysize (1190, 585)`,
##       `fit "contain"`). Não aumente esse tamanho além do espaço da folha,
##       senão a imagem invade/cobre a moldura de fora.

default persistent.diario_paginas = ["images/diariopagina1.png"]
default diario_pagina_atual = 0

## Migração: quem já tinha jogado com versões antigas deste sistema ficou
## com valores errados salvos em persistent.diario_paginas:
##   - "img_diario_dentro"  (nome de arquivo de antes de renomear)
##   - "diariopagina1"      (nome de tag, sem o caminho "images/...png")
## Nenhum dos dois funciona com `renpy.loadable()` (ver comentário lá em
## cima), então a página caía sempre no placeholder. Este bloco corrige o
## persistent de quem já tinha uma dessas entradas, sem precisar apagar save.
init python:
    if persistent.diario_paginas:
        _migracao_nomes_diario = {
            "img_diario_dentro": "images/diariopagina1.png",
            "diariopagina1": "images/diariopagina1.png",
        }
        persistent.diario_paginas = [
            _migracao_nomes_diario.get(p, p) for p in persistent.diario_paginas
        ]


screen botao_perfil():
    # Ícone do diário — canto superior direito (overlay de tela cheia)
    imagebutton:
        idle "gui/details/diario_button.png"
        hover "gui/details/diario_button_hover.png"
        focus_mask True
        action [Show("perfil_janela"), SetVariable("diario_pagina_atual", 0)]


screen barra_atributo(nome, valor):
    vbox:
        spacing 2
        hbox:
            spacing 5
            text nome style "perfil_atributo_nome" xsize 100
            text "[valor]/100" style "perfil_atributo_valor" xsize 50 xalign 1.0
        
        bar:
            xsize 220
            ysize 12
            value valor
            range 100
            left_bar Frame("gui/bar/left.png", 6, 6)
            right_bar Frame("gui/bar/right.png", 12, 6)
            thumb Frame("gui/bar/thumb.png", 6, 6)
            thumb_shadow Frame("gui/bar/thumb_shadow.png", 6, 6)


screen perfil_janela():
    modal True
    zorder 200

    # Fundo escuro com overlay
    add Solid("#000000") at fade_bg

    # 📖 Moldura exterior do livro com sombra
    frame:
        at book_entrance
        xalign 0.5
        yalign 0.5
        xsize 1280
        ysize 760
        background Frame("gui/frame.png", 20, 20)
        padding (30, 30)

        vbox:
            xfill True
            yfill True
            spacing 0

            # 🎨 CAPA DO LIVRO - Estilo Diário
            frame:
                xfill True
                ysize 80
                background Solid("#2d1f15")
                padding (20, 15)

                hbox:
                    xfill True
                    spacing 20

                    text _("📖 DIÁRIO"):
                        style "perfil_livro_titulo"
                        yalign 0.5

                    null:
                        xfill True

                    textbutton "✕":
                        action Hide("perfil_janela")
                        style "botao_fechar_livro"
                        background None
                        xalign 1.0
                        yalign 0.5

            # 🔖 Divisor decorativo
            frame:
                xfill True
                ysize 3
                background Solid("#8b5a2b")

            $ paginas_diario = persistent.diario_paginas or []
            $ total_paginas_diario = len(paginas_diario)
            $ pagina_diario = (
                  paginas_diario[diario_pagina_atual]
                  if 0 <= diario_pagina_atual < total_paginas_diario
                  else None
              )

            # 📄 PÁGINA DO DIÁRIO — camada de DENTRO (a "folha"). A imagem tem
            # que caber aqui dentro (xysize 1190x585); não aumentar esse
            # tamanho, senão ela passa por cima da moldura de fora do livro.
            frame:
                xfill True
                yfill True
                background Solid("#f0e8d8")
                padding (15, 15)

                if pagina_diario and renpy.loadable(pagina_diario):
                    add pagina_diario:
                        fit "contain"
                        xysize (1190, 585)
                        xalign 0.5
                        yalign 0.5
                else:
                    text _("Nenhuma página do diário ainda."):
                        style "livro_placeholder"
                        xalign 0.5
                        yalign 0.5


                # ‹ Página anterior
                if diario_pagina_atual > 0:
                    textbutton "‹":
                        action SetVariable("diario_pagina_atual", diario_pagina_atual - 1)
                        style "botao_fechar_livro"
                        background None
                        xalign 0.0
                        yalign 0.5

                # › Próxima página
                if diario_pagina_atual < total_paginas_diario - 1:
                    textbutton "›":
                        action SetVariable("diario_pagina_atual", diario_pagina_atual + 1)
                        style "botao_fechar_livro"
                        background None
                        xalign 1.0
                        yalign 0.5

