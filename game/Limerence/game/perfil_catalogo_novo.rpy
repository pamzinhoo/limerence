################################################################################
## Catálogo de Personagens — Estilo Carrossel (Inventory)
## Layout: 1920x1080 | Ren'Py 8.x
################################################################################

## ── Som e Funções ───────────────────────────────────────────────────────────
init python:
    # Som de página
    PAGE_FLIP_SOUND = None
    
    def play_page_flip():
        if PAGE_FLIP_SOUND and renpy.loadable(PAGE_FLIP_SOUND):
            renpy.sound.play(PAGE_FLIP_SOUND, channel="sound")

## ── Dados dos personagens ────────────────────────────────────────────────────
init python:
    personagens_lista = [
        "Pam",
        "Nao sei",
        "Maya",
        "Ethan",
        "Diretor",
        "???",
    ]

    personagens_dados = {
        "Pam": {
            "foto":        "images/protaF.png",
            "nome":        "Pam",
            "descricao":   "alguma coisa aqui",
            "historia":    "historia do rdr2",
            "curiosidade": "ela é uma pessoa",
            "bloqueado":   False,
            "genero":      "mulher",
            "sexualidade": "Bissexual",
            "ocupacao":    "Estudante",
            "especie":     "Humana",
            "personalidade": {
                "Gentileza":    80,
                "Inteligência": 85,
                "Seriedade":    70,
                "Humor":        60,
                "Saúde":        75,
            },
            "anatomia": {
                "altura":      "1.65m",
                "peso":        "55kg",
                "raca":        "Branca/Europeia",
                "tipo_sangue": "A+",
            },
        },
        "Nao sei": {
            "foto":        "protaM.png",
            "nome":        "Prota M",
            "descricao":   "descricao_aqui",
            "historia":    "historia_aqui",
            "curiosidade": "curiosidades_aqui",
            "bloqueado":   False,
            "genero":      "homem",
            "sexualidade": "Heterossexual",
            "ocupacao":    "Estudante",
            "especie":     "Humana",
            "personalidade": {
                "Gentileza":    70,
                "Inteligência": 90,
                "Seriedade":    80,
                "Humor":        50,
                "Saúde":        80,
            },
            "anatomia": {
                "altura":      "1.75m",
                "peso":        "70kg",
                "raca":        "Asiática/Japonesa",
                "tipo_sangue": "O-",
            },
        },
        "Maya": {
            "foto":        "foto_personagem_aqui",
            "nome":        "Maya",
            "descricao":   "descricao_aqui",
            "historia":    "historia_aqui",
            "curiosidade": "curiosidades_aqui",
            "bloqueado":   False,
            "genero":      "genero_aqui",
            "sexualidade": "sexualidade_aqui",
            "ocupacao":    "ocupacao_aqui",
            "especie":     "especie_aqui",
            "personalidade": {
                "Gentileza":    50,
                "Inteligência": 50,
                "Seriedade":    50,
                "Humor":        50,
                "Saúde":        50,
            },
            "anatomia": {
                "altura":      "altura_aqui",
                "peso":        "peso_aqui",
                "raca":        "raca_aqui",
                "tipo_sangue": "tipo_sangue_aqui",
            },
        },
        "Ethan": {
            "foto":        "foto_personagem_aqui",
            "nome":        "Ethan",
            "descricao":   "descricao_aqui",
            "historia":    "historia_aqui",
            "curiosidade": "curiosidades_aqui",
            "bloqueado":   False,
            "genero":      "genero_aqui",
            "sexualidade": "sexualidade_aqui",
            "ocupacao":    "ocupacao_aqui",
            "especie":     "especie_aqui",
            "personalidade": {
                "Gentileza":    50,
                "Inteligência": 50,
                "Seriedade":    50,
                "Humor":        50,
                "Saúde":        50,
            },
            "anatomia": {
                "altura":      "altura_aqui",
                "peso":        "peso_aqui",
                "raca":        "raca_aqui",
                "tipo_sangue": "tipo_sangue_aqui",
            },
        },
        "Diretor": {
            "foto":        "foto_personagem_aqui",
            "nome":        "Diretor",
            "descricao":   "descricao_aqui",
            "historia":    "historia_aqui",
            "curiosidade": "curiosidades_aqui",
            "bloqueado":   False,
            "genero":      "genero_aqui",
            "sexualidade": "sexualidade_aqui",
            "ocupacao":    "ocupacao_aqui",
            "especie":     "especie_aqui",
            "personalidade": {
                "Gentileza":    50,
                "Inteligência": 50,
                "Seriedade":    50,
                "Humor":        50,
                "Saúde":        50,
            },
            "anatomia": {
                "altura":      "altura_aqui",
                "peso":        "peso_aqui",
                "raca":        "raca_aqui",
                "tipo_sangue": "tipo_sangue_aqui",
            },
        },
        "???": {
            "foto":        "foto_personagem_aqui",
            "nome":        "???",
            "descricao":   "— BLOQUEADO —",
            "historia":    "Desbloqueie este personagem para ler mais.",
            "curiosidade": "...",
            "bloqueado":   True,
            "genero":      "???",
            "sexualidade": "???",
            "ocupacao":    "???",
            "especie":     "???",
            "personalidade": {
                "Gentileza":    0,
                "Inteligência": 0,
                "Seriedade":    0,
                "Humor":        0,
                "Saúde":        0,
            },
            "anatomia": {
                "altura":      "???",
                "peso":        "???",
                "raca":        "???",
                "tipo_sangue": "???",
            },
        },
    }

    lugares_lista = [
        "Escola",
        "Parque",
        "Casa",
        "Biblioteca",
        "Cafeteria",
    ]

    lugares_dados = {
        "Escola": {
            "foto":        "images/escola.png",
            "nome":        "Escola",
            "descricao":   "O local onde os estudantes passam a maior parte do tempo.",
            "historia":    "Uma escola típica com salas de aula e pátios.",
            "curiosidade": "Fundada em 1990.",
            "bloqueado":   False,
        },
        "Parque": {
            "foto":        "images/parque.png",
            "nome":        "Parque",
            "descricao":   "Um lugar relaxante para passear.",
            "historia":    "Um parque público com árvores e bancos.",
            "curiosidade": "Tem um lago no centro.",
            "bloqueado":   False,
        },
        "Casa": {
            "foto":        "images/casa.png",
            "nome":        "Casa",
            "descricao":   "O lar dos personagens.",
            "historia":    "Uma casa confortável na cidade.",
            "curiosidade": "Tem um jardim pequeno.",
            "bloqueado":   False,
        },
        "Biblioteca": {
            "foto":        "images/biblioteca.png",
            "nome":        "Biblioteca",
            "descricao":   "Um lugar para estudo e leitura.",
            "historia":    "Biblioteca da escola com muitos livros.",
            "curiosidade": "Tem seções especiais para estudantes.",
            "bloqueado":   False,
        },
        "Cafeteria": {
            "foto":        "images/cafeteria.png",
            "nome":        "Cafeteria",
            "descricao":   "Onde os estudantes comem.",
            "historia":    "Cafeteria da escola com comida variada.",
            "curiosidade": "Serve lanches saudáveis.",
            "bloqueado":   False,
        },
    }

    rotas_lista = [
        "Rota de Pam",
        "Rota de Maya",
        "Rota de Ethan",
        "Rota do Diretor",
        "Rota Neutra",
    ]

    rotas_dados = {
        "Rota de Pam": {
            "foto":        "images/protaF.png",
            "nome":        "Rota de Pam",
            "descricao":   "Foco na relação com Pam, a protagonista feminina.",
            "historia":    "Explore a história de Pam e suas interações.",
            "curiosidade": "Uma rota romântica e emocional.",
            "bloqueado":   False,
        },
        "Rota de Maya": {
            "foto":        "foto_personagem_aqui",
            "nome":        "Rota de Maya",
            "descricao":   "Aventure-se na rota de Maya.",
            "historia":    "Descubra os segredos de Maya.",
            "curiosidade": "Uma rota misteriosa.",
            "bloqueado":   False,
        },
        "Rota de Ethan": {
            "foto":        "foto_personagem_aqui",
            "nome":        "Rota de Ethan",
            "descricao":   "Siga a rota de Ethan.",
            "historia":    "Acompanhe as aventuras de Ethan.",
            "curiosidade": "Uma rota de ação.",
            "bloqueado":   False,
        },
        "Rota do Diretor": {
            "foto":        "foto_personagem_aqui",
            "nome":        "Rota do Diretor",
            "descricao":   "Investigue a rota do Diretor.",
            "historia":    "Revele os planos do Diretor.",
            "curiosidade": "Uma rota conspiratória.",
            "bloqueado":   False,
        },
        "Rota Neutra": {
            "foto":        "foto_personagem_aqui",
            "nome":        "Rota Neutra",
            "descricao":   "Uma rota sem foco romântico.",
            "historia":    "Explore o mundo sem compromissos.",
            "curiosidade": "Para jogadores casuais.",
            "bloqueado":   False,
        },
    }

## ── Transformações/Animações ────────────────────────────────────────────────

## Animação de zoom no hover
transform card_hover_zoom:
    zoom 1.0
    on hover:
        ease 0.2 zoom 1.1
    on idle:
        ease 0.2 zoom 1.0
## ── Estilos ─────────────────────────────────────────────────────────────────
style info_label is default:
    size 18
    color "#00AAE2"
    font "fonts/fonte.ttf"

style info_text is default:
    size 15
    color "#cccccc"

## ── Tela principal - Carrossel ──────────────────────────────────────────────
screen perfil_catalogo():
    tag menu
    modal False

    # Fundo
    add "images/background_catalogo.png" xpos 0 ypos 0 xysize (1920, 1080)

    default personagem_selecionado = "Pam"
    default carrossel_idx = 0
    default tab = "personagens"
    default lugar_selecionado = "Escola"
    default carrossel_idx_lugares = 0
    default rota_selecionada = "Rota de Pam"
    default carrossel_idx_rotas = 0

    $ tc_personagens = "#00AAE2" if tab == "personagens" else "#000000"
    $ tc_lugares = "#00AAE2" if tab == "lugares" else "#000000"
    $ tc_rotas = "#00AAE2" if tab == "rotas" else "#000000"

    # Abas sobre as faixas brancas da lateral
    textbutton _("PERSONAGENS"):
        xpos 20
        ypos 254
        xsize 330
        ysize 70
        background None
        text_style "load_nav_text"
        text_size 30
        text_color tc_personagens
        at button_hover_scale
        action SetScreenVariable("tab", "personagens")

    textbutton _("LUGARES"):
        xpos 20
        ypos 359
        xsize 330
        ysize 70
        background None
        text_style "load_nav_text"
        text_size 30
        text_color tc_lugares
        at button_hover_scale
        action SetScreenVariable("tab", "lugares")

    textbutton _("ROTAS"):
        xpos 20
        ypos 465
        xsize 330
        ysize 70
        background None
        text_style "load_nav_text"
        text_size 30
        text_color tc_rotas
        at button_hover_scale
        action SetScreenVariable("tab", "rotas")

    # Botão voltar sobre a faixa branca de baixo
    textbutton _("VOLTAR"):
        xpos 20
        ypos 1000
        xsize 330
        ysize 70
        background None
        text_style "load_nav_text"
        text_size 30
        at button_hover_scale
        action Return()

    # Título centralizado sobre a página
    text _("CATÁLOGO"):
        xpos 1200
        xanchor 0.5
        ypos 30
        size 50
        color "#ffffff"
        font "fonts/fonte.ttf"

    # ════════════════════════════════════════════════════════════════════════════
    # CARROSSEL DE PERSONAGENS
    # ════════════════════════════════════════════════════════════════════════════

    if tab == "personagens":

        $ max_visible = 3

        # Botão anterior
        textbutton "◄":
            xpos 490
            ypos 475
            xysize (80, 150)
            background None
            text_size 48
            text_color "#ffffff"
            text_hover_color "#00AAE2"
            action SetScreenVariable("carrossel_idx",
                    len(personagens_lista) - max_visible if carrossel_idx <= 0 else carrossel_idx - 1)

        # Frame carrossel
        frame:
            xpos 590
            ypos 150
            xsize 1220
            ysize 800
            background "#00000000"

            hbox:
                spacing 0
                xalign 0.5
                yalign 0.5

                $ max_visible = 3
                $ start_idx = carrossel_idx
                $ end_idx = min(len(personagens_lista), start_idx + max_visible)

                for i in range(start_idx, end_idx):
                    $ char_nome = personagens_lista[i]
                    $ char_data = personagens_dados[char_nome]
                    $ is_selected = (char_nome == personagem_selecionado)
                    $ foto = char_data["foto"]
                    $ bloqueado = char_data["bloqueado"]

                    button:
                        at card_hover_zoom
                        action [SetScreenVariable("personagem_selecionado", char_nome), Show("detalhes_perfil", data=char_data)]

                        frame:
                            if is_selected:
                                background "#ffffff33"
                                xysize (400, 660)
                                padding (12, 12, 12, 12)
                            else:
                                background "#1a1a1a"
                                xysize (380, 640)
                                padding (10, 10, 10, 10)
                                xalign 0.0
                                yalign 0.5

                            vbox:
                                spacing 0
                                xfill True
                                yfill True

                                # Foto
                                frame:
                                    background "#0a0a0a"
                                    xysize (360, 540)

                                    if not bloqueado and renpy.loadable(foto):
                                        add foto:
                                            xysize (360, 540)
                                    else:
                                        text "???":

                                            size 100
                                            color "#555555"
                                            xalign 0.5
                                            yalign 0.5

                                # Nome
                                text _(char_nome):
                                    size 18
                                    color "#ffffff"
                                    xalign 0.5
                                    yalign 0.5

        # Botão próximo
        textbutton "►":
            xpos 1830
            ypos 475
            xysize (80, 150)
            background None
            text_size 48
            text_color "#ffffff"
            text_hover_color "#00AAE2"
            action SetScreenVariable("carrossel_idx",
                    0 if carrossel_idx >= len(personagens_lista) - max_visible else carrossel_idx + 1)

    elif tab == "lugares":

        $ max_visible = 3

        # Botão anterior lugares
        textbutton "◄":
            xpos 490
            ypos 475
            xysize (80, 150)
            background None
            text_size 48
            text_color "#ffffff"
            text_hover_color "#00AAE2"
            action SetScreenVariable("carrossel_idx_lugares",
                    max(0, len(lugares_lista) - max_visible) if carrossel_idx_lugares <= 0 else carrossel_idx_lugares - 1)

        # Frame carrossel lugares
        frame:
            xpos 590
            ypos 150
            xsize 1220
            ysize 800
            background "#00000000"

            hbox:
                spacing 0
                xalign 0.5
                yalign 0.5

                $ max_visible = 3
                $ start_idx = carrossel_idx_lugares
                $ end_idx = min(len(lugares_lista), start_idx + max_visible)

                for i in range(start_idx, end_idx):
                    $ lugar_nome = lugares_lista[i]
                    $ lugar_data = lugares_dados[lugar_nome]
                    $ is_selected = (lugar_nome == lugar_selecionado)
                    $ foto = lugar_data["foto"]
                    $ bloqueado = lugar_data["bloqueado"]

                    button:
                        at card_hover_zoom
                        action [SetScreenVariable("lugar_selecionado", lugar_nome), Show("detalhes_perfil", data=lugar_data)]

                        frame:
                            if is_selected:
                                background "#ffffff33"
                                xysize (400, 660)
                                padding (12, 12, 12, 12)
                            else:
                                background "#1a1a1a"
                                xysize (380, 640)
                                padding (10, 10, 10, 10)
                                xalign 0.0
                                yalign 0.5

                            vbox:
                                spacing 0
                                xfill True
                                yfill True

                                # Foto
                                frame:
                                    background "#0a0a0a"
                                    xysize (360, 540)

                                    if not bloqueado and renpy.loadable(foto):
                                        add foto:
                                            xysize (360, 540)
                                    else:
                                        text "???":

                                            size 100
                                            color "#555555"
                                            xalign 0.5
                                            yalign 0.5

                                # Nome
                                text _(lugar_nome):
                                    size 18
                                    color "#ffffff"
                                    xalign 0.5
                                    yalign 0.5

        # Botão próximo lugares
        textbutton "►":
            xpos 1830
            ypos 475
            xysize (80, 150)
            background None
            text_size 48
            text_color "#ffffff"
            text_hover_color "#00AAE2"
            action SetScreenVariable("carrossel_idx_lugares",
                    0 if carrossel_idx_lugares >= len(lugares_lista) - max_visible else carrossel_idx_lugares + 1)

    elif tab == "rotas":

        $ max_visible = 3

        # Botão anterior rotas
        textbutton "◄":
            xpos 490
            ypos 475
            xysize (80, 150)
            background None
            text_size 48
            text_color "#ffffff"
            text_hover_color "#00AAE2"
            action SetScreenVariable("carrossel_idx_rotas",
                    max(0, len(rotas_lista) - max_visible) if carrossel_idx_rotas <= 0 else carrossel_idx_rotas - 1)

        # Frame carrossel rotas
        frame:
            xpos 590
            ypos 150
            xsize 1220
            ysize 800
            background "#00000000"

            hbox:
                spacing 0
                xalign 0.5
                yalign 0.5

                $ max_visible = 3
                $ start_idx = carrossel_idx_rotas
                $ end_idx = min(len(rotas_lista), start_idx + max_visible)

                for i in range(start_idx, end_idx):
                    $ rota_nome = rotas_lista[i]
                    $ rota_data = rotas_dados[rota_nome]
                    $ is_selected = (rota_nome == rota_selecionada)
                    $ foto = rota_data["foto"]
                    $ bloqueado = rota_data["bloqueado"]

                    button:
                        at card_hover_zoom
                        action [SetScreenVariable("rota_selecionada", rota_nome), Show("detalhes_perfil", data=rota_data)]

                        frame:
                            if is_selected:
                                background "#ffffff33"
                                xysize (400, 660)
                                padding (12, 12, 12, 12)
                            else:
                                background "#1a1a1a"
                                xysize (380, 640)
                                padding (10, 10, 10, 10)
                                xalign 0.0
                                yalign 0.5

                            vbox:
                                spacing 0
                                xfill True
                                yfill True

                                # Foto
                                frame:
                                    background "#0a0a0a"
                                    xysize (360, 540)

                                    if not bloqueado and renpy.loadable(foto):
                                        add foto:
                                            xysize (360, 540)
                                    else:
                                        text "???":

                                            size 100
                                            color "#555555"
                                            xalign 0.5
                                            yalign 0.5

                                # Nome
                                text _(rota_nome):
                                    size 18
                                    color "#ffffff"
                                    xalign 0.5
                                    yalign 0.5

        # Botão próximo rotas
        textbutton "►":
            xpos 1830
            ypos 475
            xysize (80, 150)
            background None
            text_size 48
            text_color "#ffffff"
            text_hover_color "#00AAE2"
            action SetScreenVariable("carrossel_idx_rotas",
                    0 if carrossel_idx_rotas >= len(rotas_lista) - max_visible else carrossel_idx_rotas + 1)

    # ════════════════════════════════════════════════════════════════════════════
    # PAINEL DE DETALHES REMOVIDO - AGORA EM TELA SEPARADA
    # ════════════════════════════════════════════════════════════════════════════

################################################################################
## CATÁLOGO COM CARROSSEL HORIZONTAL
################################################################################
##
## ✨ RECURSOS:
##   ✓ 5 cartas visíveis no carrossel
##   ✓ Navegação com setas (◄ ►)
##   ✓ Animação suave ao trocar
##   ✓ Som integrável
##   ✓ Painel de detalhes scrollável
##
## 🔊 SOM (OPCIONAL):
##   Adicione em: game/audio/page_flip.ogg
##   Altere linha 11: PAGE_FLIP_SOUND = "audio/page_flip.ogg"
##
################################################################################
## Foto do Pam carrega perfeitamente | Cantos "L" elegantes
################################################################################

## ── Barra de atributo da ficha ──────────────────────────────────────────────
screen barra_atributo_ficha(nome, valor):
    vbox:
        spacing 3
        hbox:
            spacing 5
            text _(nome):
                style "livro_atributo_nome"
                xsize 140
            text (str(valor) + "/100"):
                style "livro_atributo_valor"
                xsize 80
                xalign 1.0

        bar:
            xsize 440
            ysize 10
            value valor
            range 100
            left_bar Frame("gui/bar/left.png", 6, 6)
            right_bar Frame("gui/bar/right.png", 12, 6)
            thumb Frame("gui/bar/thumb.png", 6, 6)
            thumb_shadow Frame("gui/bar/thumb_shadow.png", 6, 6)


## ── Tela de Detalhes ────────────────────────────────────────────────────────
screen detalhes_perfil(data):
    modal True
    zorder 150

    add Solid("#000000aa")

    frame:
        xpos 160
        ypos 80
        xsize 1600
        ysize 900
        background Frame("gui/frame.png", 20, 20)
        padding (24, 24, 24, 24)

        vbox:
            spacing 20
            xfill True
            yfill True

            # Cabeçalho em estilo livro
            frame:
                background Solid("#2d1f15")
                xfill True
                ysize 80
                padding (20, 16)

                hbox:
                    spacing 20
                    xfill True
                    yfill True

                    text "📖 " + _(data["nome"]):
                        style "perfil_livro_titulo"
                        yalign 0.5

                    null:
                        xfill True

                    textbutton "✕":
                        style "botao_fechar_livro"
                        text_color "#c8b89a"
                        xalign 1.0
                        action Hide("detalhes_perfil")

            frame:
                background Solid("#8b5a2b")
                xfill True
                ysize 3

            hbox:
                spacing 20
                xfill True
                yfill True

                # Página esquerda com foto
                frame:
                    background Solid("#f0e8d8")
                    xsize 520
                    yfill True
                    padding (24, 24, 24, 24)

                    vbox:
                        spacing 20
                        xfill True
                        yfill True

                        if not data["bloqueado"] and renpy.loadable(data["foto"]):
                            add data["foto"]:
                                xysize (460, 460)
                                xalign 0.5
                                yalign 0.5
                        else:
                            text "???:":
                                size 110
                                color "#555555"
                                xalign 0.5
                                yalign 0.5

                $ tem_ficha = ("genero" in data) or ("personalidade" in data) or ("anatomia" in data)

                # Página do meio com descrição
                frame:
                    background Solid("#111111")
                    if tem_ficha:
                        xsize 400
                    else:
                        xfill True
                    yfill True
                    padding (24, 24, 24, 24)

                    viewport:
                        xfill True
                        yfill True
                        mousewheel True
                        draggable True

                        vbox:
                            spacing 18

                            text _("Descrição"):
                                style "perfil_secao_titulo"

                            text _(data["descricao"]):
                                style "perfil_label"

                            text _("História"):
                                style "perfil_secao_titulo"

                            text _(data["historia"]):
                                style "perfil_label"

                            text _("Curiosidades"):
                                style "perfil_secao_titulo"

                            text _(data["curiosidade"]):
                                style "perfil_label"

                # Página direita com a ficha (informações/personalidade/anatomia)
                if tem_ficha:
                    frame:
                        background Solid("#efe6d3")
                        xfill True
                        yfill True
                        padding (24, 24, 24, 24)

                        viewport:
                            xfill True
                            yfill True
                            scrollbars "vertical"
                            mousewheel True
                            draggable True

                            vbox:
                                xfill True
                                spacing 14

                                if "genero" in data:
                                    frame:
                                        xfill True
                                        background Solid("#e3d7c0")
                                        padding (14, 12)

                                        vbox:
                                            spacing 6
                                            xfill True

                                            text _("INFORMAÇÕES"):
                                                style "livro_secao_titulo"

                                            frame:
                                                xfill True
                                                ysize 1
                                                background Solid("#8b5a2b")

                                            text _("Gênero: ") + _(data.get("genero", "?")):
                                                style "livro_info_texto"

                                            text _("Sexualidade: ") + _(data.get("sexualidade", "?")):
                                                style "livro_info_texto"

                                            text _("Ocupação: ") + _(data.get("ocupacao", "?")):
                                                style "livro_info_texto"

                                            text _("Espécie: ") + _(data.get("especie", "?")):
                                                style "livro_info_texto"

                                if "personalidade" in data:
                                    frame:
                                        xfill True
                                        background Solid("#e3d7c0")
                                        padding (14, 12)

                                        vbox:
                                            spacing 8
                                            xfill True

                                            text _("PERSONALIDADE"):
                                                style "livro_secao_titulo"

                                            frame:
                                                xfill True
                                                ysize 1
                                                background Solid("#8b5a2b")

                                            for atributo, valor in data["personalidade"].items():
                                                use barra_atributo_ficha(atributo, valor)

                                if "anatomia" in data:
                                    frame:
                                        xfill True
                                        background Solid("#e3d7c0")
                                        padding (14, 12)

                                        vbox:
                                            spacing 6
                                            xfill True

                                            text _("ANATOMIA"):
                                                style "livro_secao_titulo"

                                            frame:
                                                xfill True
                                                ysize 1
                                                background Solid("#8b5a2b")

                                            text _("Altura: ") + _(data["anatomia"].get("altura", "?")):
                                                style "livro_info_texto"

                                            text _("Peso: ") + _(data["anatomia"].get("peso", "?")):
                                                style "livro_info_texto"

                                            text _("Raça: ") + _(data["anatomia"].get("raca", "?")):
                                                style "livro_info_texto"

                                            text _("Tipo Sanguíneo: ") + _(data["anatomia"].get("tipo_sangue", "?")):
                                                style "livro_info_texto"