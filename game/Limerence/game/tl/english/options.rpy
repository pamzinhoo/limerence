# ARQUIVO: options.rpy

## This file contains options that can be changed to customize the game.
##
## Lines that begin with two '#' marks are comments and you should not
## uncomment them. Lines that begin with a single '#' are commented-out
## code, and you may want to uncomment them when appropriate.


## Basics ######################################################################

## A human-readable name for the game. This is used to set the default
## window title and appears in the interface and error reports.
##
## The _() surrounding the string marks it as eligible for translation.

define config.name = _("VnGame")


## Determines if the title given above is shown on the main menu screen.
## Set this to False to hide the title.

define gui.show_name = True


## The version of the game.

define config.version = "1.0"


## Text that is placed on the game's "About" screen. Put the text between
## triple quotes and leave a blank line between paragraphs.

define gui.about = _p("""
""")


## A short name for the game used for executables and directories in the
## built distribution. It should contain only ASCII characters and should not
## contain spaces, colons, or semicolons.

define build.name = "VnGame"


## Sounds and Music ############################################################

## These three variables control, among other things, which mixers are
## shown to the player by default. Setting one of these to False will hide
## the appropriate mixer.

define config.has_sound = True
define config.has_music = True
define config.has_voice = True


## To allow the user to play a test sound on the sound or voice channel,
## uncomment the line below and use it to define a sample sound to be played.

# define config.sample_sound = "sample-sound.ogg"
# define config.sample_voice = "sample-voice.ogg"


## Uncomment the following line to set an audio file that will be played
## while the player is at the main menu. This file will continue playing
## into the game until it is stopped or another file is played.

# define config.main_menu_music = "main-menu-theme.ogg"


## Transitions #################################################################
##
## These variables set the transitions that are used when certain
## events occur. Each variable should be set to a transition or None
## to indicate that no transition should be used.

## Entering and exiting the game menu.

define config.enter_transition = dissolve
define config.exit_transition = dissolve


## Between screens of the game menu.

define config.intra_transition = dissolve


## A transition that is used after a game is loaded.

define config.after_load_transition = None


## Used when entering the main menu after the game ends.

define config.end_game_transition = None


## There is no variable to set the transition used when the game starts.
## Instead, use a with statement after showing the initial scene.


## Window Management ###########################################################
##
## This controls when the dialogue window is displayed. If it is "show",
## it will always be displayed. If it is "hide", it will only be displayed
## when dialogue is present. If it is "auto", the window will be hidden
## before scene statements and shown again when dialogue is displayed.
##
## After the game starts, this can be changed with the "window show",
## "window hide", and "window auto" statements.

define config.window = "auto"


## Transitions used to show and hide the dialogue window.

define config.window_show_transition = Dissolve(.2)
define config.window_hide_transition = Dissolve(.2)


## Preference Defaults #########################################################

## Controls the default text speed. The default, 0, is infinite, while
## any other number is the number of characters per second to type.

default preferences.text_cps = 0


## The default auto-forward delay. Higher numbers lead to longer waits,
## with 0 to 30 being the valid range.

default preferences.afm_time = 15


## Save Directory ##############################################################
##
## Controls the platform-specific location where Ren'Py will place save
## files for this game. Save files will be placed in:
##
## Windows: %APPDATA\\RenPy\\<config.save_directory>
##
## Macintosh: $HOME/Library/RenPy/<config.save_directory>
##
## Linux: $HOME/.renpy/<config.save_directory>
##
## This generally should not be changed and, if it is, should always be a
## literal string, not an expression.

define config.save_directory = "VnGame-1773776130"


## Icon ########################################################################
##
## The icon displayed on the taskbar or dock.

define config.window_icon = "gui/window_icon.png"


## Build Configuration #########################################################
##
## This section controls how Ren'Py turns your project into distribution files.

init python:

    ## The following functions take file patterns. File patterns
    ## are case-insensitive and are matched against the relative path
    ## to the base directory, with and without a leading /. If multiple
    ## patterns match, the first one is used.
    ##
    ## In a pattern:
    ##
    ## / is the directory separator.
    ##
    ## * matches all characters except the directory separator.
    ##
    ## ** matches all characters, including the directory separator.
    ##
    ## For example, "*.txt" matches txt files in the base directory,
    ## "game/**.ogg" matches ogg files in the game directory or any
    ## of its subdirectories, and "**.psd" matches psd files anywhere
    ## in the project.

    ## Classify files as None to exclude them from built distributions.

    build.classify('**~', None)
    build.classify('**.bak', None)
    build.classify('**/.**', None)
    build.classify('**/#**', None)
    build.classify('**/thumbs.db', None)

    ## To archive files, classify them as "archive".

    # build.classify('game/**.png', 'archive')
    # build.classify('game/**.jpg', 'archive')

    ## Files matching documentation patterns are duplicated
    ## in a Mac app build so they appear both inside the app
    ## and the zip file.

    build.documentation('*.html')
    build.documentation('*.txt')


## A Google Play license key is required to perform in-app purchases.
## It can be found in the Google Play developer console under:
## "Monetize" > "Monetization setup" > "Licensing".

# define build.google_play_key = "..."


## The username and project name associated with an itch.io project,
## separated by a slash.

# define build.itch_project = "renpytom/test-project"


# TODO: Translation updated at 2026-05-14 08:38

translate english strings:

    # game/options.rpy:15
    old "VnGame"
    new "VnGame"