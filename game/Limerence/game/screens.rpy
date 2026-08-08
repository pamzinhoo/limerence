################################################################################
## Inicialização
################################################################################

init offset = -1


################################################################################
## Estilos
################################################################################
default easter_egg_visto = False
style default:
    properties gui.text_properties()
    language gui.language

style input:
    properties gui.text_properties("input", accent=True)
    adjust_spacing False

style hyperlink_text:
    properties gui.text_properties("hyperlink", accent=True)
    hover_underline True

style gui_text:
    properties gui.text_properties("interface")


style button:
    properties gui.button_properties("button")

style button_text is gui_text:
    properties gui.text_properties("button")
    yalign 0.5


style label_text is gui_text:
    properties gui.text_properties("label", accent=True)

style prompt_text is gui_text:
    properties gui.text_properties("prompt")


style bar:
    ysize gui.bar_size
    left_bar Frame("gui/bar/left.png", gui.bar_borders, tile=gui.bar_tile)
    right_bar Frame("gui/bar/right.png", gui.bar_borders, tile=gui.bar_tile)

style vbar:
    xsize gui.bar_size
    top_bar Frame("gui/bar/top.png", gui.vbar_borders, tile=gui.bar_tile)
    bottom_bar Frame("gui/bar/bottom.png", gui.vbar_borders, tile=gui.bar_tile)

style scrollbar:
    ysize gui.scrollbar_size
    base_bar Frame("gui/scrollbar/horizontal_[prefix_]bar.png", gui.scrollbar_borders, tile=gui.scrollbar_tile)
    thumb Frame("gui/scrollbar/horizontal_[prefix_]thumb.png", gui.scrollbar_borders, tile=gui.scrollbar_tile)

style vscrollbar:
    xsize gui.scrollbar_size
    base_bar Frame("gui/scrollbar/vertical_[prefix_]bar.png", gui.vscrollbar_borders, tile=gui.scrollbar_tile)
    thumb Frame("gui/scrollbar/vertical_[prefix_]thumb.png", gui.vscrollbar_borders, tile=gui.scrollbar_tile)

style slider:
    ysize gui.slider_size
    base_bar Frame("gui/slider/horizontal_[prefix_]bar.png", gui.slider_borders, tile=gui.slider_tile)
    thumb "gui/slider/horizontal_[prefix_]thumb.png"

style vslider:
    xsize gui.slider_size
    base_bar Frame("gui/slider/vertical_[prefix_]bar.png", gui.vslider_borders, tile=gui.slider_tile)
    thumb "gui/slider/vertical_[prefix_]thumb.png"


style frame:
    padding gui.frame_borders.padding
    background Frame("gui/frame.png", gui.frame_borders, tile=gui.frame_tile)



################################################################################
## Telas no jogo
################################################################################


## Diga a tela #################################################################
##
## A tela say é usada para exibir o diálogo para o jogador. Ela recebe dois
## parâmetros, who e what, que são o nome do personagem que fala e o texto a ser
## exibido, respectivamente. (O parâmetro who pode ser None (Nenhum) se nenhum
## nome for fornecido).
##
## Essa tela deve criar um texto exibível com o id "what", pois o Ren'Py o
## utiliza para gerenciar a exibição de texto. Ela também pode criar exibíveis
## com id "who" e id "window" para aplicar propriedades de estilo.
##
## https://www.renpy.org/doc/html/screen_special.html#say

screen say(who, what):

    window:
        id "window"
        

        text what id "what":
            style "say_dialogue"    # ← dentro da window ✓
            color "#ffffff"

    if who is not None:
        text who:
            id "who"
            style "say_label"
            xpos 541
            xanchor 0.5
            ypos 745
            yanchor 0.5
            color "#0099cc"
            

    if not renpy.variant("small"):
        add SideImage() xalign 0.0 yalign 0.30


## Disponibilize a caixa de nome para estilização por meio do objeto Character.
init python:
    config.character_id_prefixes.append('namebox')

init python:
    config.game_menu_action = ShowMenu("in_game_menu")

style window is default
style say_label is default
style say_dialogue is default
style say_thought is say_dialogue

style namebox is default
style namebox_label is say_label


style window:
    xalign 0.5
    xfill True
    yalign gui.textbox_yalign
    ysize gui.textbox_height

    background Image("gui/details/textbox_ui.png", xalign=0.5, yalign=1.0)

style namebox:
    xpos gui.name_xpos
    xanchor gui.name_xalign
    xsize gui.namebox_width
    ypos -80
    ysize gui.namebox_height

    background Frame("gui/namebox.png", gui.namebox_borders, tile=gui.namebox_tile, xalign=gui.name_xalign)
    padding gui.namebox_borders.padding

style say_label:
    properties gui.text_properties("name", accent=True)
    xalign gui.name_xalign
    yalign 0.5

style say_dialogue:
    properties gui.text_properties("dialogue")

    xpos gui.dialogue_xpos
    xsize gui.dialogue_width
    ypos gui.dialogue_ypos

    adjust_spacing False

## Tela de entrada #############################################################
##
## Essa tela é usada para exibir renpy.input. O parâmetro prompt é usado para
## passar um prompt de texto.
##
## Essa tela deve criar um displayable de entrada com id "input" para aceitar os
## vários parâmetros de entrada.
##
## https://www.renpy.org/doc/html/screen_special.html#input

screen input(prompt):
    style_prefix "input"

    window:

        vbox:
            xanchor gui.dialogue_text_xalign
            xpos gui.dialogue_xpos
            xsize gui.dialogue_width
            ypos gui.dialogue_ypos

            text prompt style "input_prompt"
            input id "input"

style input_prompt is default

style input_prompt:
    xalign gui.dialogue_text_xalign
    properties gui.text_properties("input_prompt")

style input:
    xalign gui.dialogue_text_xalign
    xmaximum gui.dialogue_width


## Tela de escolha #############################################################
##
## Essa tela é usada para exibir as opções no jogo apresentadas pela instrução
## de menu. O único parâmetro, itens, é uma lista de objetos, cada um com campos
## de legenda e ação.
##
## https://www.renpy.org/doc/html/screen_special.html#choice

screen choice(items):
    style_prefix "choice"

    vbox:
        for i in items:
            textbutton i.caption action i.action


style choice_vbox is vbox
style choice_button is button
style choice_button_text is button_text

style choice_vbox:
    xalign 0.5
    ypos 405
    yanchor 0.5

    spacing gui.choice_spacing

style choice_button is default:
    properties gui.button_properties("choice_button")

style choice_button_text is default:
    properties gui.text_properties("choice_button")


## Tela do menu rápido #########################################################
##
## O menu rápido é exibido no jogo para fornecer acesso fácil aos menus fora do menu QUE TEM QUANDO INICIA O JOGO NA PARTE DE BAIXO DA TELA
## jogo.

screen quick_menu():

    ## Certifique-se de que isso apareça na parte superior de outras telas.
    zorder 100

    ## Ícones de canto (no lugar da antiga barra de botões). São overlays de
    ## tela cheia com o ícone já posicionado; focus_mask deixa só o ícone clicável.
    ## Só aparecem quando há diálogo na tela (tela "say" ativa).
    if quick_menu and renpy.get_screen("say"):

        # Tecla P mostra/esconde o botão de configurações
        key "p" action SetVariable("mostrar_config", not mostrar_config)
        key "P" action SetVariable("mostrar_config", not mostrar_config)

        # Salvar — canto inferior esquerdo
        imagebutton:
            idle "gui/details/save_button.png"
            hover "gui/details/save_button_hover.png"
            focus_mask True
            action ShowMenu('save')

        # Início / voltar ao menu — canto inferior direito
        imagebutton:
            idle "gui/details/menu_button.png"
            hover "gui/details/menu_button_hover.png"
            focus_mask True
            action MainMenu(confirm=True)

        # Configurações (skip / Ctrl) — só aparece ao apertar P
        if mostrar_config:
            imagebutton:
                idle "gui/details/config_button.png"
                hover "gui/details/config_button_hover.png"
                focus_mask True
                action ShowMenu('preferences')

        # Diário — canto superior direito. O selo de "atualizado" fica dentro
        # do mesmo `fixed` que o botão (mesmo espaço/tamanho de antes dentro
        # do quick_menu), assim ele não desalinha o resto dos ícones.
        fixed:
            imagebutton:
                idle "gui/details/diario_button.png"
                hover "gui/details/diario_button_hover.png"
                focus_mask True
                # Abre o diário na primeira página e desliga o selo de "atualizado"
                action [
                    Show("perfil_janela"),
                    SetField(persistent, "diario_notificacao", False),
                    SetVariable("diario_pagina_atual", 0),
                ]

            # Selo de "diário atualizado" — logo abaixo do ícone do diário.
            # Liga/desliga via `persistent.diario_notificacao`. Para reativar
            # em qualquer ponto do roteiro (nova página do diário, etc.),
            # chame `diario_notificar()` (definida em perfil.rpy).
            if persistent.diario_notificacao:
                add "images/diarioselo.png":
                    xysize (65, 62)
                    fit "contain"
                    xpos 1868
                    xanchor 0.5
                    ypos 84


## Esse código garante que a tela quick_menu seja exibida no jogo, sempre que o
## jogador não tiver ocultado explicitamente a interface.
init python:
    config.overlay_screens.append("quick_menu")

default quick_menu = True

## Controla a visibilidade do botão de configurações (alternado pela tecla P).
default mostrar_config = False

style quick_menu is hbox
style quick_button is default
style quick_button_text is button_text

style quick_menu:
    xalign 0.5
    yalign 1.0

style quick_button:
    properties gui.button_properties("quick_button")

style quick_button_text:
    properties gui.text_properties("quick_button")


################################################################################
## Telas do menu principal e do menu do jogo
################################################################################

## Tela de navegação ###########################################################
##
## Essa tela está incluída nos menus principal e do jogo e fornece navegação
## para outros menus e para iniciar o jogo.

screen navigation():

    vbox:
        style_prefix "navigation" 

        xpos gui.navigation_xpos
        yalign 0.5

        spacing gui.navigation_spacing

        if main_menu:

            textbutton _("Início") action Start()

        else:

            textbutton _("Histórico") action ShowMenu("history")

            textbutton _("Salvar") action ShowMenu("save")

        textbutton _("Carga") action ShowMenu("load")

        textbutton _("Preferências") action ShowMenu("preferences")

        textbutton _("Catálogo") action ShowMenu("perfil_catalogo") 

        if _in_replay:

            textbutton _("Fim da reprodução") action EndReplay(confirm=True)

        elif not main_menu:

            textbutton _("Menu principal") action MainMenu()

        textbutton _("Sobre") action ShowMenu("about")

        if renpy.variant("pc") or (renpy.variant("web") and not renpy.variant("mobile")):

            ## A ajuda não é necessária ou relevante para dispositivos móveis.
            textbutton _("Ajuda") action ShowMenu("help")

        if renpy.variant("pc"):

            ## O botão Sair é proibido no iOS e desnecessário no Android e na
            ## Web.
            textbutton _("Sair") action Quit(confirm=not main_menu)


style navigation_button is gui_button
style navigation_button_text is gui_button_text

style navigation_button:
    size_group "navigation"
    properties gui.button_properties("navigation_button")

style navigation_button_text:
    properties gui.text_properties("navigation_button")


## Tela do menu principal ######################################################
##
## Usado para exibir o menu principal quando o Ren'Py é iniciado.
##
## https://www.renpy.org/doc/html/screen_special.html#main-menu
transform button_hover_scale:
    zoom 1.0
    subpixel True
    on hover:
        ease 0.15 zoom 1.08 xoffset -2 yoffset -3
    on idle:
        ease 0.15 zoom 1.0 xoffset 0 yoffset 0
screen main_menu(): 

    tag menu

    if not easter_egg_visto:
        timer 10800.0 action ShowMenu("easter_egg")
    add Movie(play="videos/main_menu.webm", loop=True) xysize (1920, 1080) xalign 0.5 yalign 0.5


    add "gui/overlay/nenhum_selecionado.png" xalign 0.5 yalign 0.5 alpha 0.7

    frame:
        style "main_menu_frame"
        
    fixed:
        textbutton _("Início") action Start():
            style "main_menu_button"
            xpos 0
            ypos 310
            at button_hover_scale

        textbutton _("Carregar") action ShowMenu('load'):
            style "main_menu_button"
            xpos 0
            ypos 425
            at button_hover_scale
            
        textbutton _("Preferências") action ShowMenu('preferences'):
            style "main_menu_button"
            xpos 0
            ypos 540
            at button_hover_scale


        textbutton _("Catálogo") action ShowMenu('perfil_catalogo'):
            style "main_menu_button"
            xpos 0
            ypos 650
            at button_hover_scale
        
        textbutton _("Sobre") action ShowMenu('about'):
            style "main_menu_button"
            xpos 0
            ypos 750
            at button_hover_scale
        textbutton _("Ajuda") action ShowMenu('help'):
            style "main_menu_button"
            xpos 0
            ypos 863
            at button_hover_scale
        textbutton _("Sair") action Quit(confirm=True):
            style "main_menu_button"
            xpos 0
            ypos 980
            at button_hover_scale

    


style main_menu_frame is empty
style main_menu_vbox is vbox
style main_menu_text is gui_text
style main_menu_title is main_menu_text
style main_menu_version is main_menu_text
style main_menu_button is gui_button
style main_menu_button_text is gui_button_text

style main_menu_frame:
    xsize 420
    yfill True

style main_menu_vbox:
    xalign 0.0
    xoffset 60
    yalign 0.0
    yoffset 200
    spacing 5

style main_menu_text:
    properties gui.text_properties("main_menu", accent=True)
    font "fonts/fonte.ttf"

style main_menu_button:
    properties gui.button_properties("button")
    ysize 80
    xsize 360

style main_menu_button_text:
    font "fonts/fonte.ttf"
    size 45
    color "#000000"
    hover_color "#7C7A8D"
    xalign 0.5
    text_align 0.5

style main_menu_title:
    properties gui.text_properties("title")

style main_menu_version:
    properties gui.text_properties("version")


## Tela de Aviso ##############################################################
##
## Tela que exibe a imagem de aviso de conteúdo.

screen tela_aviso():
    modal True
    add "aviso.png" xysize (1920, 1080)


## Tela do menu do jogo ########################################################
##
## Isso estabelece a estrutura básica comum de uma tela de menu de jogo. Ela
## é chamada com o título da tela e exibe o plano de fundo, o título e a
## navegação.
##
## O parâmetro de rolagem pode ser Nenhum ou um dos parâmetros "viewport"
## ou "vpgrid". Essa tela deve ser usada com um ou mais filhos, que são
## transcluídos (colocados) dentro dela.

screen game_menu(title, scroll=None, yinitial=0.0, spacing=0):

    style_prefix "game_menu"

    if main_menu:
        add gui.main_menu_background
    else:
        add gui.game_menu_background

    frame:
        style "game_menu_outer_frame"

        hbox:
            frame:
                style "game_menu_navigation_frame"

            frame:
                style "game_menu_content_frame"

                if scroll == "viewport":
                    viewport:
                        yinitial yinitial
                        scrollbars "vertical"
                        mousewheel True
                        draggable True
                        pagekeys True
                        side_yfill True
                        vbox:
                            spacing spacing
                            transclude

                elif scroll == "vpgrid":
                    vpgrid:
                        cols 1
                        yinitial yinitial
                        scrollbars "vertical"
                        mousewheel True
                        draggable True
                        pagekeys True
                        side_yfill True
                        spacing spacing
                        transclude

                else:
                    transclude

    if main_menu:
        key "game_menu" action ShowMenu("main_menu")
    else:
        key "game_menu" action ShowMenu("in_game_menu")


## Tela de pause menu (botão direito durante o jogo)
screen in_game_menu():
    tag menu
    modal True

    add gui.game_menu_background

    frame:
        style "game_menu_outer_frame"
        hbox:
            frame:
                style "game_menu_navigation_frame"
            frame:
                style "game_menu_content_frame"

    fixed:
        textbutton _("Início") action ShowMenu("save"):
            xpos 50
            ypos 265
            xsize 310
            ysize 70
            text_style "load_nav_text"
            at button_hover_scale

        textbutton _("Carga") action ShowMenu("load"):
            xpos 50
            ypos 370
            xsize 310
            ysize 70
            text_style "load_nav_text"
            at button_hover_scale

        textbutton _("Preferências") action ShowMenu("preferences"):
            xpos 50
            ypos 473
            xsize 310
            ysize 70
            text_style "load_nav_text"
            at button_hover_scale

        textbutton _("Catálogo") action ShowMenu("perfil_catalogo"):
            xpos 50
            ypos 580
            xsize 310
            ysize 70
            text_style "load_nav_text"
            at button_hover_scale

        textbutton _("Sobre") action ShowMenu("about"):
            xpos 50
            ypos 685
            xsize 310
            ysize 70
            text_style "load_nav_text"
            at button_hover_scale

        textbutton _("Ajuda") action ShowMenu("help"):
            xpos 50
            ypos 785
            xsize 310
            ysize 70
            text_style "load_nav_text"
            at button_hover_scale

        textbutton _("Menu Principal") action MainMenu():
            xpos 50
            ypos 890
            xsize 310
            ysize 70
            text_style "load_nav_text"
            at button_hover_scale

        textbutton _("Voltar") action Return():
            xpos 50
            ypos 990
            xsize 310
            ysize 70
            text_style "load_nav_text"
            at button_hover_scale


style game_menu_outer_frame is empty
style game_menu_navigation_frame is empty
style game_menu_content_frame is empty
style game_menu_viewport is gui_viewport
style game_menu_side is gui_side
style game_menu_scrollbar is gui_vscrollbar

style game_menu_label is gui_label
style game_menu_label_text is gui_label_text

style return_button is navigation_button
style return_button_text is navigation_button_text

style game_menu_outer_frame:
    bottom_padding 45
    top_padding 180

    background "gui/overlay/game_menu.png"

style game_menu_navigation_frame:
    xsize 420
    yfill True

style game_menu_content_frame:
    left_margin 60
    right_margin 30
    top_margin 15

style game_menu_viewport:
    xsize 1380

style game_menu_vscrollbar:
    unscrollable gui.unscrollable

style game_menu_side:
    spacing 15

style game_menu_label:
    xpos 75
    ysize 180

style game_menu_label_text:
    size 75
    color gui.accent_color
    yalign 0.5

style return_button:
    xpos gui.navigation_xpos
    yalign 1.0
    yoffset -45


## Sobre a tela ################################################################
##
## Essa tela fornece informações de crédito e direitos autorais sobre o jogo e
## Ren'Py.
##
## Não há nada de especial nessa tela e, portanto, ela também serve como exemplo
## de como criar uma tela personalizada.

screen about(): 

    tag menu

    use game_menu(_(""), scroll="viewport"):

        style_prefix "about"

        vbox:
            xpos 0.02
            ypos 0.6
            label "[config.name!t]"
            text _("Versão [config.version!t]\n")

            if gui.about:
                text "[gui.about!t]\n"

            text _("Feito com {a=https://www.renpy.org/}Ren'Py{/a} [renpy.version_only] .\n\n[renpy.license!t]") #textinho do bolso

    fixed:
        textbutton _("Início") action Return():
            xpos 50
            ypos 265
            xsize 310
            text_style "load_nav_text"
            at button_hover_scale

        textbutton _("Carga") action ShowMenu("load"):
            xpos 50
            ypos 370
            xsize 310
            text_style "load_nav_text"
            at button_hover_scale

        textbutton _("Preferências") action ShowMenu("preferences"):
            xpos 50
            ypos 473
            xsize 310
            text_style "load_nav_text"
            at button_hover_scale

        textbutton _("Catálogo") action ShowMenu("perfil_catalogo"):
            xpos 50
            ypos 580
            xsize 310
            text_style "load_nav_text"
            at button_hover_scale

        textbutton _("Sobre") action ShowMenu("about"):
            xpos 50
            ypos 685
            xsize 310
            text_style "load_nav_text"
            at button_hover_scale

        textbutton _("Ajuda") action ShowMenu("help"):
            xpos 50
            ypos 785
            xsize 310
            text_style "load_nav_text"
            at button_hover_scale

        textbutton _("Sair") action Quit(confirm=True):
            xpos 50
            ypos 890
            xsize 310
            text_style "load_nav_text"
            at button_hover_scale

        textbutton _("Voltar") action Return():
            xpos 150
            ypos 995
            text_style "load_nav_text"
            at button_hover_scale


style about_label is gui_label
style about_label_text is gui_label_text
style about_text is gui_text

style about_label_text:
    size gui.label_text_size


## Carregar e salvar telas #####################################################
##
## Essas telas são responsáveis por permitir que o jogador salve o jogo
## e o carregue novamente. Como elas têm quase tudo em comum, ambas são
## implementadas em termos de uma terceira tela, file_slots.
##
## https://www.renpy.org/doc/html/screen_special.html#save https://
## www.renpy.org/doc/html/screen_special.html#load

screen save():

    tag menu

    # Background
    add "gui/overlay/game_menu.png" xpos 0 ypos 0 xsize 1920 ysize 1080

    # Botões da sidebar
    textbutton _("Histórico") action ShowMenu("history"):
        xpos 50
        ypos 265
        xsize 310
        ysize 70
        text_style "load_nav_text"
        at button_hover_scale

    textbutton _("Carga") action ShowMenu("load"):
        xpos 50
        ypos 370
        xsize 310
        ysize 70
        text_style "load_nav_text"
        at button_hover_scale

    textbutton _("Preferências") action ShowMenu("preferences"):
        xpos 50
        ypos 473
        xsize 310
        ysize 70
        text_style "load_nav_text"
        at button_hover_scale

    textbutton _("Catálogo") action ShowMenu("perfil_catalogo"):
        xpos 50
        ypos 580
        xsize 310
        ysize 70
        text_style "load_nav_text"
        at button_hover_scale

    textbutton _("Sobre") action ShowMenu("about"):
        xpos 50
        ypos 685
        xsize 310
        ysize 70
        text_style "load_nav_text"
        at button_hover_scale

    textbutton _("Ajuda") action ShowMenu("help"):
        xpos 50
        ypos 785
        xsize 310
        ysize 70
        text_style "load_nav_text"
        at button_hover_scale

    textbutton _("Sair") action Quit(confirm=True):
        xpos 50
        ypos 890
        xsize 310
        ysize 70
        text_style "load_nav_text"
        at button_hover_scale

    textbutton _("Voltar") action Return():
        xpos 150
        ypos 995
        text_style "load_nav_text"
        at button_hover_scale

    # Slots de arquivo
    fixed:
        xpos 650
        ypos 185

        default page_name_value = FilePageNameInputValue(
            pattern=_("Página {}"),
            auto=_("Salvamentos automáticos"),
            quick=_("Salvamentos rápidos")
        )

        button:
            style "page_label"
            xpos 636
            xanchor 0.5
            key_events True
            action page_name_value.Toggle()
            input:
                style "page_label_text"
                value page_name_value

        grid gui.file_slot_cols gui.file_slot_rows:
            style_prefix "slot"
            xpos 0
            ypos 50
            spacing gui.slot_spacing

            for i in range(gui.file_slot_cols * gui.file_slot_rows):
                $ slot = i + 1
                button:
                    action FileAction(slot)
                    has vbox
                    add FileScreenshot(slot) xalign 0.5
                    text FileTime(slot, format=_("{#file_time}%A, %B %d %Y, %H:%M"), empty=_("slot vazio")):
                        style "slot_time_text"
                    text FileSaveName(slot):
                        style "slot_name_text"
                    key "save_delete" action FileDelete(slot)

        hbox:
            style_prefix "page"
            xpos 636
            xanchor 0.5
            ypos 630
            spacing gui.page_spacing

            textbutton _("<") action FilePagePrevious()
            if config.has_autosave:
                textbutton _("{#auto_page}A") action FilePage("auto")
            if config.has_quicksave:
                textbutton _("{#quick_page}Q") action FilePage("quick")
            for page in range(1, 10):
                textbutton "[page]" action FilePage(page)
            textbutton _(">") action FilePageNext()

        if config.has_sync:
            textbutton _("Upload Sync"):
                action UploadSync()
                xalign 0.5
                ypos 700

screen load(): 
    tag menu

    # Background
    add "gui/overlay/game_menu.png" xpos 0 ypos 0 xsize 1920 ysize 1080

    # Título
    

    # Botões da sidebar (um por retângulo)
    textbutton _("Histórico") action ShowMenu("history"):
        xpos 50
        ypos 265    # ← retângulo 1
        xsize 310
        ysize 70
        text_style "load_nav_text"
        at button_hover_scale

    textbutton _("Carga") action ShowMenu("load"):
        xpos 50
        ypos 370    # ← retângulo 2
        xsize 310
        ysize 70
        text_style "load_nav_text"
        at button_hover_scale

    textbutton _("Preferências") action ShowMenu("preferences"):
        xpos 50
        ypos 473     # ← retângulo 3
        xsize 310
        ysize 70
        text_style "load_nav_text"
        at button_hover_scale

    textbutton _("Catálogo") action ShowMenu("perfil_catalogo"):
        xpos 50
        ypos 580    # ← retângulo 4
        xsize 310
        ysize 70
        text_style "load_nav_text"
        at button_hover_scale

    textbutton _("Sobre") action ShowMenu("about"):
        xpos 50
        ypos 685     # ← retângulo 5
        xsize 310
        ysize 70
        text_style "load_nav_text"
        at button_hover_scale

    textbutton _("Ajuda") action ShowMenu("help"):
        xpos 50
        ypos 785    # ← retângulo 6
        xsize 310
        ysize 70
        text_style "load_nav_text"
        at button_hover_scale

    textbutton _("Sair") action Quit(confirm=True):
        xpos 50
        ypos 890     # ← retângulo 7
        xsize 310
        ysize 70
        text_style "load_nav_text"
        at button_hover_scale

    # textbutton _("Sair") action Quit(confirm=True):
    #     xpos 50
    #     ypos 975      # ← retângulo 8
    #     xsize 290
    #     text_style "load_nav_text"

    # Botão Voltar
    textbutton _("Voltar") action Return():
        xpos 150
        ypos 995
        text_style "load_nav_text"
        at button_hover_scale

    # Slots de arquivo
    fixed:
        xpos 650
        ypos 185

        default page_name_value = FilePageNameInputValue(
            pattern=_("Página {}"),
            auto=_("Salvamentos automáticos"),
            quick=_("Salvamentos rápidos")
        )

        button:
            style "page_label"
            xpos 636
            xanchor 0.5
            key_events True
            action page_name_value.Toggle()
            input:
                style "page_label_text"
                value page_name_value

        grid gui.file_slot_cols gui.file_slot_rows:
            style_prefix "slot"
            xpos 0
            ypos 50
            spacing gui.slot_spacing

            for i in range(gui.file_slot_cols * gui.file_slot_rows):
                $ slot = i + 1
                button:
                    action FileAction(slot)
                    has vbox
                    add FileScreenshot(slot) xalign 0.5
                    text FileTime(slot, format=_("{#file_time}%A, %B %d %Y, %H:%M"), empty=_("slot vazio")):
                        style "slot_time_text"
                    text FileSaveName(slot):
                        style "slot_name_text"
                    key "save_delete" action FileDelete(slot)

        hbox:
            style_prefix "page"
            xpos 636
            xanchor 0.5
            ypos 630
            spacing gui.page_spacing

            textbutton _("<") action FilePagePrevious()
            for page in range(1, 10):
                textbutton "[page]" action FilePage(page)
            textbutton _(">") action FilePageNext()

style load_nav_text:
    color "#000000"
    hover_color "#222222"
    size 40
    font "fonts/fonte.ttf"
    xalign 0.5
    yalign 0.5


screen file_slots(title):

    default page_name_value = FilePageNameInputValue(pattern=_("Página {}"), auto=_("Salvamentos automáticos"), quick=_("Salvamentos rápidos"))

    use game_menu(title):

        fixed:

            ## Isso garante que a entrada receberá o evento enter antes de
            ## qualquer um dos botões.
            order_reverse True

            ## O nome da página, que pode ser editado clicando em um botão.
            button:
                style "page_label"

                key_events True
                xalign 0.5
                action page_name_value.Toggle()

                input:
                    style "page_label_text"
                    value page_name_value

            ## A grade de slots de arquivo.
            grid gui.file_slot_cols gui.file_slot_rows:
                style_prefix "slot"

                xalign 0.5
                yalign 0.5

                spacing gui.slot_spacing

                for i in range(gui.file_slot_cols * gui.file_slot_rows):

                    $ slot = i + 1

                    button:
                        action FileAction(slot)

                        has vbox

                        add FileScreenshot(slot) xalign 0.5

                        text FileTime(slot, format=_("{#file_time}%A, %B %d %Y, %H:%M"), empty=_("slot vazio")):
                            style "slot_time_text"

                        text FileSaveName(slot):
                            style "slot_name_text"

                        key "save_delete" action FileDelete(slot)

            ## Botões para acessar outras páginas.
            vbox:
                style_prefix "page"

                xalign 0.5
                yalign 1.0

                hbox:
                    xalign 0.5

                    spacing gui.page_spacing

                    textbutton _("<") action FilePagePrevious()
                    key "save_page_prev" action FilePagePrevious()

                    if config.has_autosave:
                        textbutton _("{#auto_page}A") action FilePage("auto")

                    if config.has_quicksave:
                        textbutton _("{#quick_page}Q") action FilePage("quick")

                    ## range(1, 10) fornece os números de 1 a 9.
                    for page in range(1, 10):
                        textbutton "[page]" action FilePage(page)

                    textbutton _(">") action FilePageNext()
                    key "save_page_next" action FilePageNext()

                if config.has_sync:
                    if CurrentScreenName() == "save":
                        textbutton _("Upload Sync"):
                            action UploadSync()
                            xalign 0.5
                    else:
                        textbutton _("Baixar o Sync"):
                            action DownloadSync()
                            xalign 0.5


style page_label is gui_label
style page_label_text is gui_label_text
style page_button is gui_button
style page_button_text is gui_button_text

style slot_button is gui_button
style slot_button_text is gui_button_text
style slot_time_text is slot_button_text
style slot_name_text is slot_button_text

style page_label:
    xpadding 75
    ypadding 5
    xalign 0.5

style page_label_text:
    textalign 0.5
    layout "subtitle"
    hover_color gui.hover_color

style page_button:
    properties gui.button_properties("page_button")

style page_button_text:
    properties gui.text_properties("page_button")

style slot_button:
    properties gui.button_properties("slot_button")

style slot_button_text:
    properties gui.text_properties("slot_button")


## Tela de preferências ########################################################
##
## A tela de preferências permite que o jogador configure o jogo para se adequar
## melhor.
##
## https://www.renpy.org/doc/html/screen_special.html#preferences

screen preferences(): 

    tag menu

    
    use game_menu(_(""), scroll="viewport"):
    
        vbox:
            xpos 0.1
            ypos 0.1
            hbox:
                box_wrap True

                if renpy.variant("pc") or renpy.variant("web"):

                    vbox:
                        style_prefix "radio"
                        label _("Tela")
                        textbutton _("Janela") action Preference("display", "window")
                        textbutton _("Tela cheia") action Preference("display", "fullscreen")
                

                vbox:
                    style_prefix "check"
                    label _("Pular")
                    textbutton _("Texto invisível") action Preference("skip", "toggle")
                    textbutton _("Após as escolhas") action Preference("after choices", "toggle")
                    textbutton _("Transições") action InvertSelected(Preference("transitions", "toggle"))

                ## Vboxes adicionais do tipo "radio_pref" ou "check_pref" podem
                ## ser adicionadas aqui para acrescentar outras preferências
                ## definidas pelo criador.

                vbox:
                    style_prefix "radio"
                    label _("Idioma / Language")
                    textbutton "Português" action Language(None)
                    textbutton "English" action Language("english")

            null height (4 * gui.pref_spacing)
            hbox:
                style_prefix "slider"
                box_wrap True

                vbox:

                    label _("Velocidade do texto")

                    bar value Preference("text speed")

                    label _("Tempo de encaminhamento automático")

                    bar value Preference("auto-forward time")

                vbox:

                    if config.has_music:
                        label _("Volume da música")

                        hbox:
                            bar value Preference("music volume")

                    if config.has_sound:

                        label _("Volume do som")

                        hbox:
                            bar value Preference("sound volume")

                            if config.sample_sound:
                                textbutton _("Teste") action Play("sound", config.sample_sound)


                    if config.has_voice:
                        label _("Volume da voz")

                        hbox:
                            bar value Preference("voice volume")

                            if config.sample_voice:
                                textbutton _("Teste") action Play("voice", config.sample_voice)

                    if config.has_music or config.has_sound or config.has_voice:
                        null height gui.pref_spacing

                        textbutton _("Silenciar tudo"):
                            action Preference("all mute", "toggle")
                            style "mute_all_button"
                
    fixed:
        textbutton _("Início") action Return():
            xpos 50
            ypos 265
            xsize 310
            text_style "load_nav_text"
            at button_hover_scale

        textbutton _("Carga") action ShowMenu("load"):
            xpos 50
            ypos 370    # ← retângulo 2
            xsize 310
            text_style "load_nav_text"
            at button_hover_scale

        textbutton _("Preferências") action ShowMenu("preferences"):
            xpos 50
            ypos 473     # ← retângulo 3
            xsize 310
            text_style "load_nav_text"
            at button_hover_scale

        textbutton _("Catálogo") action ShowMenu("perfil_catalogo"):
            xpos 50
            ypos 580    # ← retângulo 4
            xsize 310
            text_style "load_nav_text"
            at button_hover_scale

        textbutton _("Sobre") action ShowMenu("about"):
            xpos 50
            ypos 685     # ← retângulo 5
            xsize 310
            text_style "load_nav_text"
            at button_hover_scale

        textbutton _("Ajuda") action ShowMenu("help"):
            xpos 50
            ypos 785    # ← retângulo 6
            xsize 310
            text_style "load_nav_text"
            at button_hover_scale

        textbutton _("Sair") action Quit(confirm=True):
            xpos 50
            ypos 890     # ← retângulo 7
            xsize 310
            text_style "load_nav_text"
            at button_hover_scale

        # textbutton _("Sair") action Quit(confirm=True):
        #     xpos 50
        #     ypos 975      # ← retângulo 8
        #     xsize 290
        #     text_style "load_nav_text"

        # Botão Voltar
        textbutton _("Voltar") action Return():
            xpos 150
            ypos 995
            text_style "load_nav_text"
            at button_hover_scale


style pref_label is gui_label
style pref_label_text is gui_label_text
style pref_vbox is vbox

style radio_label is pref_label
style radio_label_text is pref_label_text
style radio_button is gui_button
style radio_button_text is gui_button_text
style radio_vbox is pref_vbox

style check_label is pref_label
style check_label_text is pref_label_text
style check_button is gui_button
style check_button_text is gui_button_text
style check_vbox is pref_vbox

style slider_label is pref_label
style slider_label_text is pref_label_text
style slider_slider is gui_slider
style slider_button is gui_button
style slider_button_text is gui_button_text
style slider_pref_vbox is pref_vbox

style mute_all_button is check_button
style mute_all_button_text is check_button_text

style pref_label:
    top_margin gui.pref_spacing
    bottom_margin 3

style pref_label_text:
    yalign 1.0

style pref_vbox:
    xsize 338

style radio_vbox:
    spacing gui.pref_button_spacing

style radio_button:
    properties gui.button_properties("radio_button")
    foreground "gui/button/radio_[prefix_]foreground.png"

style radio_button_text:
    properties gui.text_properties("radio_button")
    

style check_vbox:
    spacing gui.pref_button_spacing

style check_button:
    properties gui.button_properties("check_button")
    foreground "gui/button/check_[prefix_]foreground.png"

style check_button_text:
    properties gui.text_properties("check_button")

style slider_slider:
    xsize 525

style slider_button:
    properties gui.button_properties("slider_button")
    yalign 0.5
    left_margin 15

style slider_button_text:
    properties gui.text_properties("slider_button")

style slider_vbox:
    xsize 675


## Tela de histórico ###########################################################
##
## Essa é uma tela que exibe o histórico de diálogo para o jogador. Embora não
## haja nada de especial nessa tela, ela precisa acessar o histórico de diálogo
## armazenado em _history_list.
##
## https://www.renpy.org/doc/html/history.html

screen history():

    tag menu
    predict False

    use game_menu(_("Histórico"), scroll=("vpgrid" if gui.history_height else "viewport"), yinitial=1.0, spacing=gui.history_spacing):

        style_prefix "history"

        for h in _history_list:

            window:
                has fixed:
                    yfit True

                if h.who:
                    label h.who:
                        style "history_name"
                        substitute False
                        if "color" in h.who_args:
                            text_color h.who_args["color"]

                $ what = renpy.filter_text_tags(h.what, allow=gui.history_allow_tags)
                text what:
                    substitute False

        if not _history_list:
            label _("O histórico de diálogo está vazio.")

    fixed:
        textbutton _("Histórico") action ShowMenu("history"):
            xpos 50
            ypos 265
            xsize 310
            ysize 70
            text_style "load_nav_text"
            at button_hover_scale

        textbutton _("Salvar") action ShowMenu("save"):
            xpos 50
            ypos 370
            xsize 310
            ysize 70
            text_style "load_nav_text"
            at button_hover_scale

        textbutton _("Carga") action ShowMenu("load"):
            xpos 50
            ypos 473
            xsize 310
            ysize 70
            text_style "load_nav_text"
            at button_hover_scale

        textbutton _("Preferências") action ShowMenu("preferences"):
            xpos 50
            ypos 580
            xsize 310
            ysize 70
            text_style "load_nav_text"
            at button_hover_scale

        textbutton _("Catálogo") action ShowMenu("perfil_catalogo"):
            xpos 50
            ypos 685
            xsize 310
            ysize 70
            text_style "load_nav_text"
            at button_hover_scale

        textbutton _("Sobre") action ShowMenu("about"):
            xpos 50
            ypos 785
            xsize 310
            ysize 70
            text_style "load_nav_text"
            at button_hover_scale

        textbutton _("Ajuda") action ShowMenu("help"):
            xpos 50
            ypos 890
            xsize 310
            ysize 70
            text_style "load_nav_text"
            at button_hover_scale

        textbutton _("Sair") action Quit(confirm=True):
            xpos 50
            ypos 995
            xsize 310
            ysize 70
            text_style "load_nav_text"
            at button_hover_scale

        

## Isso determina quais tags podem ser exibidas na tela de histórico.

define gui.history_allow_tags = { "alt", "noalt", "rt", "rb", "art" }


style history_window is empty

style history_name is gui_label
style history_name_text is gui_label_text
style history_text is gui_text

style history_label is gui_label
style history_label_text is gui_label_text

style history_window:
    xfill True
    ysize gui.history_height

style history_name:
    xpos 470
    xanchor gui.history_name_xalign
    ypos gui.history_name_ypos
    xsize gui.history_name_width

style history_name_text:
    min_width gui.history_name_width
    textalign gui.history_name_xalign

style history_text:
    xpos 720
    ypos gui.history_text_ypos
    xanchor gui.history_text_xalign
    xsize gui.history_text_width
    min_width gui.history_text_width
    textalign gui.history_text_xalign
    layout ("subtitle" if gui.history_text_xalign else "tex")

style history_label:
    xfill True

style history_label_text:
    xalign 0.5


## Tela de ajuda ###############################################################
##
## Uma tela que fornece informações sobre as combinações de teclas e mouse. Ela
## usa outras telas (keyboard_help, mouse_help e gamepad_help) para exibir a
## ajuda real.
screen easter_egg():
    add Movie(play="videos/easter-egg.webm", loop=False) xysize (1920, 1080) xalign 0.5 yalign 0.5
    timer 9.0 action [
        SetVariable("easter_egg_visto", True),
        ShowMenu("main_menu")
    ]
screen help():

    tag menu

    default device = "keyboard"

    use game_menu(_(""), scroll="viewport"):

        style_prefix "help"

        vbox:
            xpos 0.3
            ypos 6
            spacing 23

            hbox:

                textbutton _("Teclado") action SetScreenVariable("device", "keyboard")
                textbutton _("Mouse") action SetScreenVariable("device", "mouse")

                if GamepadExists():
                    textbutton _("Controle de jogo") action SetScreenVariable("device", "gamepad")

            if device == "keyboard":
                use keyboard_help
            elif device == "mouse":
                use mouse_help
            elif device == "gamepad":
                use gamepad_help

    fixed:
        textbutton _("Início") action Return():
            xpos 50
            ypos 265
            xsize 310
            text_style "load_nav_text"
            at button_hover_scale

        textbutton _("Carga") action ShowMenu("load"):
            xpos 50
            ypos 370
            xsize 310
            text_style "load_nav_text"
            at button_hover_scale

        textbutton _("Preferências") action ShowMenu("preferences"):
            xpos 50
            ypos 473
            xsize 310
            text_style "load_nav_text"
            at button_hover_scale

        textbutton _("Catálogo") action ShowMenu("perfil_catalogo"):
            xpos 50
            ypos 580
            xsize 310
            text_style "load_nav_text"
            at button_hover_scale

        textbutton _("Sobre") action ShowMenu("about"):
            xpos 50
            ypos 685
            xsize 310
            text_style "load_nav_text"
            at button_hover_scale

        textbutton _("Ajuda") action ShowMenu("help"):
            xpos 50
            ypos 785
            xsize 310
            text_style "load_nav_text"
            at button_hover_scale

        textbutton _("Sair") action Quit(confirm=True):
            xpos 50
            ypos 890
            xsize 310
            text_style "load_nav_text"
            at button_hover_scale

        textbutton _("Voltar") action Return():
            xpos 150
            ypos 995
            text_style "load_nav_text"
            at button_hover_scale


screen keyboard_help():

    hbox:
        label _("Entrar")
        text _("Avança o diálogo e ativa a interface.")

    hbox:
        label _("Espaço")
        text _("Avança o diálogo sem selecionar opções.")

    hbox:
        label _("Teclas de seta")
        text _("Navegue pela interface.")

    hbox:
        label _("Fuga")
        text _("Acessa o menu do jogo.")

    hbox:
        label _("Ctrl")
        text _("Pula o diálogo quando pressionado.")

    hbox:
        label _("Tab")
        text _("Alterna o salto de diálogo.")

    hbox:
        label _("Página para cima")
        text _("Volta ao diálogo anterior.")

    hbox:
        label _("Página para baixo")
        text _("Rola para frente o diálogo posterior.")

    hbox:
        label "H"
        text _("Oculta a interface do usuário.")

    hbox:
        label "S"
        text _("Faz uma captura de tela.")

    hbox:
        label "V"
        text _("Alterna a assistência {a=https://www.renpy.org/l/voicing}auto-voz{/a}.")

    hbox:
        label "Shift+A"
        text _("Abre o menu de acessibilidade.")


screen mouse_help():

    hbox:
        label _("Clique com o botão esquerdo do mouse")
        text _("Avança o diálogo e ativa a interface.")

    hbox:
        label _("Clique no meio")
        text _("Oculta a interface do usuário.")

    hbox:
        label _("Clique com o botão direito do mouse")
        text _("Acessa o menu do jogo.")

    hbox:
        label _("Roda do mouse para cima\nClique em Rollback Side")
        text _("Volta ao diálogo anterior.")

    hbox:
        label _("Roda do mouse para baixo")
        text _("Rola para frente o diálogo posterior.")


screen gamepad_help():

    hbox:
        label _("Gatilho direito\nBotão A/inferior")
        text _("Avança o diálogo e ativa a interface.")

    hbox:
        label _("Gatilho esquerdo\nOmbro esquerdo")
        text _("Volta ao diálogo anterior.")

    hbox:
        label _("Ombro direito")
        text _("Rola para frente o diálogo posterior.")

    hbox:
        label _("D-Pad, bastões")
        text _("Navegue pela interface.")

    hbox:
        label _("Start, Guide, B/Right Button")
        text _("Acessa o menu do jogo.")

    hbox:
        label _("Botão Y/Top")
        text _("Oculta a interface do usuário.")

    textbutton _("Calibrar") action GamepadCalibrate()


style help_button is gui_button
style help_button_text is gui_button_text
style help_label is gui_label
style help_label_text is gui_label_text
style help_text is gui_text

style help_button:
    properties gui.button_properties("help_button")
    xmargin 12

style help_button_text:
    properties gui.text_properties("help_button")

style help_label:
    xsize 375
    right_padding 30

style help_label_text:
    size gui.text_size
    xalign 1.0
    textalign 1.0



################################################################################
## Telas adicionais
################################################################################


## Confirmar tela ##############################################################
##
## A tela de confirmação é chamada quando Ren'Py quer fazer uma pergunta de sim
## ou não ao jogador.
##
## https://www.renpy.org/doc/html/screen_special.html#confirm

screen confirm(message, yes_action, no_action):

    ## Certifique-se de que outras telas não recebam entrada enquanto essa tela
    ## estiver sendo exibida.
    modal True

    zorder 200

    style_prefix "confirm"

    add "gui/overlay/confirm.png"

    frame:

        vbox:
            xalign .5
            yalign .5
            spacing 45

            label _(message):
                style "confirm_prompt"
                xalign 0.5

            hbox:
                xalign 0.5
                spacing 150

                textbutton _("Sim") action yes_action
                textbutton _("Não") action no_action

    ## Clique com o botão direito do mouse e escape a resposta "não".
    key "game_menu" action no_action


style confirm_frame is gui_frame
style confirm_prompt is gui_prompt
style confirm_prompt_text is gui_prompt_text
style confirm_button is gui_medium_button
style confirm_button_text is gui_medium_button_text

style confirm_frame:
    background Frame([ "gui/confirm_frame.png", "gui/frame.png"], gui.confirm_frame_borders, tile=gui.frame_tile)
    padding gui.confirm_frame_borders.padding
    xalign .5
    yalign .5

style confirm_prompt_text:
    textalign 0.5
    layout "subtitle"

style confirm_button:
    properties gui.button_properties("confirm_button")

style confirm_button_text:
    properties gui.text_properties("confirm_button")


## Pular a tela do indicador ###################################################
##
## A tela skip_indicator é exibida para indicar que o salto está em andamento.
##
## https://www.renpy.org/doc/html/screen_special.html#skip-indicator

screen skip_indicator():

    zorder 100
    style_prefix "skip"

    frame:

        hbox:
            spacing 9

            text _("Pular")

            text "▸" at delayed_blink(0.0, 1.0) style "skip_triangle"
            text "▸" at delayed_blink(0.2, 1.0) style "skip_triangle"
            text "▸" at delayed_blink(0.4, 1.0) style "skip_triangle"


## Essa transformação é usada para piscar as setas uma após a outra.
transform delayed_blink(delay, cycle):
    alpha .5

    pause delay

    block:
        linear .2 alpha 1.0
        pause .2
        linear .2 alpha 0.5
        pause (cycle - .4)
        repeat


style skip_frame is empty
style skip_text is gui_text
style skip_triangle is skip_text

style skip_frame:
    ypos gui.skip_ypos
    background Frame("gui/skip.png", gui.skip_frame_borders, tile=gui.frame_tile)
    padding gui.skip_frame_borders.padding

style skip_text:
    size gui.notify_text_size

style skip_triangle:
    ## Temos que usar uma fonte que tenha o glifo BLACK RIGHT-POINTING SMALL
    ## TRIANGLE.
    font "DejaVuSans.ttf"


## Tela de notificação #########################################################
##
## A tela de notificação é usada para mostrar uma mensagem ao jogador. (Por
## exemplo, quando o jogo é salvo rapidamente ou quando uma captura de tela é
## feita).
##
## https://www.renpy.org/doc/html/screen_special.html#notify-screen

screen notify(message):

    zorder 100
    style_prefix "notify"

    frame at notify_appear:
        text "[message!tq]"

    timer 3.25 action Hide('notify')


transform notify_appear:
    on show:
        alpha 0
        linear .25 alpha 1.0
    on hide:
        linear .5 alpha 0.0


style notify_frame is empty
style notify_text is gui_text

style notify_frame:
    ypos gui.notify_ypos

    background Frame("gui/notify.png", gui.notify_frame_borders, tile=gui.frame_tile)
    padding gui.notify_frame_borders.padding

style notify_text:
    properties gui.text_properties("notify")


## Tela NVL ####################################################################
##
## Essa tela é usada para o diálogo e os menus do modo NVL.
##
## https://www.renpy.org/doc/html/screen_special.html#nvl


screen nvl(dialogue, items=None):

    window:
        style "nvl_window"

        has vbox:
            spacing gui.nvl_spacing

        ## Exibe o diálogo em uma vpgrid ou na vbox.
        if gui.nvl_height:

            vpgrid:
                cols 1
                yinitial 1.0

                use nvl_dialogue(dialogue)

        else:

            use nvl_dialogue(dialogue)

        ## Exibe o menu, se fornecido. O menu poderá ser exibido incorretamente
        ## se config.narrator_menu estiver definido como True.
        for i in items:

            textbutton i.caption:
                action i.action
                style "nvl_button"

    add SideImage() xalign 0.0 yalign 1.0


screen nvl_dialogue(dialogue):

    for d in dialogue:

        window:
            id d.window_id

            fixed:
                yfit gui.nvl_height is None

                if d.who is not None:

                    text d.who:
                        id d.who_id

                text d.what:
                    id d.what_id


## Isso controla o número máximo de entradas do modo NVL que podem ser exibidas
## de uma vez.
define config.nvl_list_length = gui.nvl_list_length

style nvl_window is default
style nvl_entry is default

style nvl_label is say_label
style nvl_dialogue is say_dialogue

style nvl_button is button
style nvl_button_text is button_text

style nvl_window:
    xfill True
    yfill True

    background "gui/nvl.png"
    padding gui.nvl_borders.padding

style nvl_entry:
    xfill True
    ysize gui.nvl_height

style nvl_label:
    xpos gui.nvl_name_xpos
    xanchor gui.nvl_name_xalign
    ypos gui.nvl_name_ypos
    yanchor 0.0
    xsize gui.nvl_name_width
    min_width gui.nvl_name_width
    textalign gui.nvl_name_xalign

style nvl_dialogue:
    xpos gui.nvl_text_xpos
    xanchor gui.nvl_text_xalign
    ypos gui.nvl_text_ypos
    xsize gui.nvl_text_width
    min_width gui.nvl_text_width
    textalign gui.nvl_text_xalign
    layout ("subtitle" if gui.nvl_text_xalign else "tex")

style nvl_thought:
    xpos gui.nvl_thought_xpos
    xanchor gui.nvl_thought_xalign
    ypos gui.nvl_thought_ypos
    xsize gui.nvl_thought_width
    min_width gui.nvl_thought_width
    textalign gui.nvl_thought_xalign
    layout ("subtitle" if gui.nvl_text_xalign else "tex")

style nvl_button:
    properties gui.button_properties("nvl_button")
    xpos gui.nvl_button_xpos
    xanchor gui.nvl_button_xalign

style nvl_button_text:
    properties gui.text_properties("nvl_button")


## Tela de bolhas ##############################################################
##
## A tela de balão é usada para exibir o diálogo para o jogador ao usar balões
## de fala. A tela de bolhas recebe os mesmos parâmetros que a tela de dizer,
## deve criar um exibível com o ID de "what" e pode criar exibíveis com os IDs
## "namebox", "who" e "window".
##
## https://www.renpy.org/doc/html/bubble.html#bubble-screen

screen bubble(who, what):
    style_prefix "bubble"

    window:
        id "window"

        if who is not None:

            window:
                id "namebox"
                style "bubble_namebox"

                text who:
                    id "who"

        text what:
            id "what"

        default ctc = None
        showif ctc:
            add ctc

style bubble_window is empty
style bubble_namebox is empty
style bubble_who is default
style bubble_what is default

style bubble_window:
    xpadding 30
    top_padding 5
    bottom_padding 5

style bubble_namebox:
    xalign 0.5

style bubble_who:
    xalign 0.5
    textalign 0.5
    color "#000"

style bubble_what:
    align (0.5, 0.5)
    text_align 0.5
    layout "subtitle"
    color "#000"

define bubble.frame = Frame("gui/bubble.png", 55, 55, 55, 95)
define bubble.thoughtframe = Frame("gui/thoughtbubble.png", 55, 55, 55, 55)

define bubble.properties = {
    "bottom_left" : {
        "window_background" : Transform(bubble.frame, xzoom=1, yzoom=1),
        "window_bottom_padding" : 27,
    },

    "bottom_right" : {
        "window_background" : Transform(bubble.frame, xzoom=-1, yzoom=1),
        "window_bottom_padding" : 27,
    },

    "top_left" : {
        "window_background" : Transform(bubble.frame, xzoom=1, yzoom=-1),
        "window_top_padding" : 27,
    },

    "top_right" : {
        "window_background" : Transform(bubble.frame, xzoom=-1, yzoom=-1),
        "window_top_padding" : 27,
    },

    "thought" : {
        "window_background" : bubble.thoughtframe,
    }
}

define bubble.expand_area = {
    "bottom_left" : (0, 0, 0, 22),
    "bottom_right" : (0, 0, 0, 22),
    "top_left" : (0, 22, 0, 0),
    "top_right" : (0, 22, 0, 0),
    "thought" : (0, 0, 0, 0),
}



################################################################################
## Variantes do celular
################################################################################

style pref_vbox:
    variant "medium"
    xsize 675

## Como o mouse pode não estar presente, substituímos o menu rápido por uma
## versão que usa menos botões e maiores, que são mais fáceis de tocar.
screen quick_menu():
    variant "touch"

    zorder 100

    ## Barra de botões removida a pedido (variante touch).
    if quick_menu:
        null


style window:
    variant "small"
    background "gui/phone/textbox.png"

style radio_button:
    variant "small"
    foreground "gui/phone/button/radio_[prefix_]foreground.png"

style check_button:
    variant "small"
    foreground "gui/phone/button/check_[prefix_]foreground.png"

style nvl_window:
    variant "small"
    background "gui/phone/nvl.png"

style main_menu_frame:
    variant "small"
    background "gui/phone/overlay/main_menu.png"

style game_menu_outer_frame:
    variant "small"
    background "gui/phone/overlay/game_menu.png"

style game_menu_navigation_frame:
    variant "small"
    xsize 510

style game_menu_content_frame:
    variant "small"
    top_margin 0

style game_menu_viewport:
    variant "small"
    xsize 1305

style pref_vbox:
    variant "small"
    xsize 600

style bar:
    variant "small"
    ysize gui.bar_size
    left_bar Frame("gui/phone/bar/left.png", gui.bar_borders, tile=gui.bar_tile)
    right_bar Frame("gui/phone/bar/right.png", gui.bar_borders, tile=gui.bar_tile)

style vbar:
    variant "small"
    xsize gui.bar_size
    top_bar Frame("gui/phone/bar/top.png", gui.vbar_borders, tile=gui.bar_tile)
    bottom_bar Frame("gui/phone/bar/bottom.png", gui.vbar_borders, tile=gui.bar_tile)

style scrollbar:
    variant "small"
    ysize gui.scrollbar_size
    base_bar Frame("gui/phone/scrollbar/horizontal_[prefix_]bar.png", gui.scrollbar_borders, tile=gui.scrollbar_tile)
    thumb Frame("gui/phone/scrollbar/horizontal_[prefix_]thumb.png", gui.scrollbar_borders, tile=gui.scrollbar_tile)

style vscrollbar:
    variant "small"
    xsize gui.scrollbar_size
    base_bar Frame("gui/phone/scrollbar/vertical_[prefix_]bar.png", gui.vscrollbar_borders, tile=gui.scrollbar_tile)
    thumb Frame("gui/phone/scrollbar/vertical_[prefix_]thumb.png", gui.vscrollbar_borders, tile=gui.scrollbar_tile)

style slider:
    variant "small"
    ysize gui.slider_size
    base_bar Frame("gui/phone/slider/horizontal_[prefix_]bar.png", gui.slider_borders, tile=gui.slider_tile)
    thumb "gui/phone/slider/horizontal_[prefix_]thumb.png"

style vslider:
    variant "small"
    xsize gui.slider_size
    base_bar Frame("gui/phone/slider/vertical_[prefix_]bar.png", gui.vslider_borders, tile=gui.slider_tile)
    thumb "gui/phone/slider/vertical_[prefix_]thumb.png"

style slider_vbox:
    variant "small"
    xsize None

style slider_slider:
    variant "small"
    xsize 900
screen frase_transicao(frase):
    add "#000000"
    text frase:
        xalign 0.5
        yalign 0.5
        color "#ffffff"
        size 32
        italic True
screen horario(frase):
    add "#000000"
    text frase:
        xalign 0.5
        yalign 0.5
        color "#ffffff"
screen day_locate(local, dia):
    zorder 100
    modal False

    # Nova arte do day info (lanterna suspensa no canto superior esquerdo)
    add "gui/details/day_info.png" xpos 0 ypos 0

    # Rótulo "Dia" — dentro do vidro da lanterna
    text _("Dia"):
        xpos 57
        xanchor 0.5
        ypos 55
        yanchor 0.5
        color "#ffffff"
        size 18
        font "fonts/fonte.ttf"
        text_align 0.5

    # Número do dia — abaixo do rótulo "Dia"
    text local:
        xpos 57
        xanchor 0.5
        ypos 90
        yanchor 0.5
        color "#ffffff"
        size 32
        font "fonts/fonte.ttf"
        text_align 0.5


################################################################################
## Catálogo de Personagens
################################################################################

screen perfil_catalogo():
    modal False
    tag menu

    # Background escuro
    add "#0f0f1e"

    # Layout principal: Sidebar + Conteúdo
    fixed:
        # Sidebar esquerda
        frame:
            style "perfil_catalogo_sidebar"
            xpos 0
            ypos 0
            yfill True

            vbox:
                spacing 0
                yfill True

                # Título "Perfil" no topo
                text _("Perfil") style "perfil_catalogo_title":
                    xpos 20
                    ypos 20

                # Botões centralizados no meio
                vbox:
                    style_prefix "navigation" 

                    xpos gui.navigation_xpos
                    yalign 0.5

                    spacing gui.navigation_spacing

                    if main_menu:

                        textbutton _("Início") action Start()


                    textbutton _("Carga") action ShowMenu("load")

                    textbutton _("Preferências") action ShowMenu("preferences")
                    
                    textbutton _("Catálogo") action ShowMenu("perfil_catalogo") 

                    


                    textbutton _("Sobre") action ShowMenu("about")

                    if renpy.variant("pc") or (renpy.variant("web") and not renpy.variant("mobile")):

                        ## A ajuda não é necessária ou relevante para dispositivos móveis.
                        textbutton _("Ajuda") action ShowMenu("help")

                    if renpy.variant("pc"):

                        ## O botão Sair é proibido no iOS e desnecessário no Android e na
                        ## Web.
                        textbutton _("Sair") action Quit(confirm=not main_menu)


        # Conteúdo principal
        frame:
            xpos 850
            ypos 0
            xsize 470
            yfill True
            background None
            padding (30, 30, 2, 30)

            vbox:
                spacing 20

                # Grid de personagens
                viewport:
                    xsize 1040
                    yfill True
                    scrollbars "vertical"

                    vbox:
                        spacing 20

                        # Linha 1
                        hbox:
                            spacing 20

                            # Card 1
                            button:
                                style "perfil_catalogo_card_button"
                                action NullAction()

                                hbox:
                                    spacing 0

                                    frame:
                                        style "perfil_catalogo_card_name"
                                        text _("mulher") style "perfil_catalogo_card_name_text"

                                    frame:
                                        style "perfil_catalogo_card_photo"
                                        add "protaF.png" crop (850, 150, 1400, 900) xysize (220, 135)

                            # Card 2
                            button:
                                style "perfil_catalogo_card_button"
                                action NullAction()

                                hbox:
                                    spacing 0

                                    frame:
                                        style "perfil_catalogo_card_name"
                                        text _("nome aqui") style "perfil_catalogo_card_name_text"

                                    frame:
                                        style "perfil_catalogo_card_photo"

                        # Linha 2
                        hbox:
                            spacing 20

                            # Card 3
                            button:
                                style "perfil_catalogo_card_button"
                                action NullAction()

                                hbox:
                                    spacing 0

                                    frame:
                                        style "perfil_catalogo_card_name"
                                        text _("nome aqui") style "perfil_catalogo_card_name_text"

                                    frame:
                                        style "perfil_catalogo_card_photo"
                                        add "caminho/da/foto/aqui" crop (850, 150, 1400, 900) xysize (220, 130)

                            # Card 4
                            button:
                                style "perfil_catalogo_card_button"
                                action NullAction()

                                hbox:
                                    spacing 0

                                    frame:
                                        style "perfil_catalogo_card_name"
                                        text _("nome aqui") style "perfil_catalogo_card_name_text"

                                    frame:
                                        style "perfil_catalogo_card_photo"
                                        add "caminho/da/foto/aqui" crop (850, 150, 1400, 900) xysize (220, 130)

                        # Linha 3
                        hbox:
                            spacing 20

                            # Card 5
                            button:
                                style "perfil_catalogo_card_button"
                                action NullAction()

                                hbox:
                                    spacing 0

                                    frame:
                                        style "perfil_catalogo_card_name"
                                        text _("nome aqui") style "perfil_catalogo_card_name_text"

                                    frame:
                                        style "perfil_catalogo_card_photo"
                                        add "caminho/da/foto/aqui" crop (850, 150, 1400, 900) xysize (220, 130)

                            # Card 6
                            button:
                                style "perfil_catalogo_card_button"
                                action NullAction()

                                hbox:
                                    spacing 0

                                    frame:
                                        style "perfil_catalogo_card_name"
                                        text _("nome aqui") style "perfil_catalogo_card_name_text"

                                    frame:
                                        style "perfil_catalogo_card_photo"
                                        add "caminho/da/foto/aqui" crop (850, 150, 1400, 900) xysize (220, 130)

                        # Linha 4
                        hbox:
                            spacing 20

                            # Card 7
                            button:
                                style "perfil_catalogo_card_button"
                                action NullAction()

                                hbox:
                                    spacing 0

                                    frame:
                                        style "perfil_catalogo_card_name"
                                        text _("nome aqui") style "perfil_catalogo_card_name_text"

                                    frame:
                                        style "perfil_catalogo_card_photo"
                                        add "caminho/da/foto/aqui" crop (850, 150, 1400, 900) xysize (220, 130)

                            # Card 8
                            button:
                                style "perfil_catalogo_card_button"
                                action NullAction()

                                hbox:
                                    spacing 0

                                    frame:
                                        style "perfil_catalogo_card_name"
                                        text _("nome aqui") style "perfil_catalogo_card_name_text"

                                    frame:
                                        style "perfil_catalogo_card_photo"
                                        add "caminho/da/foto/aqui" crop (850, 150, 1400, 900) xysize (220, 130)

                        # Linha 5
                        hbox:
                            spacing 20

                            # Card 9
                            button:
                                style "perfil_catalogo_card_button"
                                action NullAction()

                                hbox:
                                    spacing 0

                                    frame:
                                        style "perfil_catalogo_card_name"
                                        text _("nome aqui") style "perfil_catalogo_card_name_text"

                                    frame:
                                        style "perfil_catalogo_card_photo"
                                        add "caminho/da/foto/aqui" crop (850, 150, 1400, 900) xysize (220, 130)

                            # Card 10
                            button:
                                style "perfil_catalogo_card_button"
                                action NullAction()

                                hbox:
                                    spacing 0

                                    frame:
                                        style "perfil_catalogo_card_name"
                                        text _("nome aqui") style "perfil_catalogo_card_name_text"

                                    frame:
                                        style "perfil_catalogo_card_photo"
                                        add "caminho/da/foto/aqui" crop (850, 150, 1400, 900) xysize (220, 130)
                        # linha 6
                        hbox:
                            spacing 20

                            # Card 11
                            button:
                                style "perfil_catalogo_card_button"
                                action NullAction()

                                hbox:
                                    spacing 0

                                    frame:
                                        style "perfil_catalogo_card_name"
                                        text _("nome aqui") style "perfil_catalogo_card_name_text"

                                    frame:
                                        style "perfil_catalogo_card_photo"
                                        add "caminho/da/foto/aqui" crop (850, 150, 1400, 900) xysize (220, 130)

                            # Card 12
                            button:
                                style "perfil_catalogo_card_button"
                                action NullAction()

                                hbox:
                                    spacing 0

                                    frame:
                                        style "perfil_catalogo_card_name"
                                        text _("nome aqui") style "perfil_catalogo_card_name_text"

                                    frame:
                                        style "perfil_catalogo_card_photo"
                                        add "caminho/da/foto/aqui" crop (850, 150, 1400, 900) xysize (220, 130)

                        # linha 7
                        hbox:
                            spacing 20

                            # Card 13
                            button:
                                style "perfil_catalogo_card_button"
                                action NullAction()

                                hbox:
                                    spacing 0

                                    frame:
                                        style "perfil_catalogo_card_name"
                                        text _("nome aqui") style "perfil_catalogo_card_name_text"

                                    frame:
                                        style "perfil_catalogo_card_photo"
                                        add "caminho/da/foto/aqui" crop (850, 150, 1400, 900) xysize (220, 130)

                            # Card 14
                            button:
                                style "perfil_catalogo_card_button"
                                action NullAction()

                                hbox:
                                    spacing 0

                                    frame:
                                        style "perfil_catalogo_card_name"
                                        text _("nome aqui") style "perfil_catalogo_card_name_text"

                                    frame:
                                        style "perfil_catalogo_card_photo"
                                        add "caminho/da/foto/aqui" crop (850, 150, 1400, 900) xysize (220, 130)                