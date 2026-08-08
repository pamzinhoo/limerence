# ARQUIVO: kinetic_text_tags.rpy

"""
 Kinetic Text Tags Ren'Py Module
 2021 Daniel Westfall <SoDaRa2595@gmail.com>

 http://twitter.com/sodara9
 I'd appreciate being given credit if you do end up using it! :D Would really
 make my day to know I helped some people out!
 Really hope this can help the community create some really neat ways to spice
 up their dialogue!
 http://opensource.org/licenses/mit-license.php
 Forum Post: https://lemmasoft.renai.us/forums/viewtopic.php?f=51&t=60527&sid=75b4eb1aa5212a33cbfe9b0354e5376b
 Github: https://github.com/SoDaRa/Kinetic-Text-Tags
 itch.io: https://wattson.itch.io/kinetic-text-tags
"""

# Permission is hereby granted, free of charge, to any person
# obtaining a copy of this software and associated documentation files
# (the "Software"), to deal in the Software without restriction,
# including without limitation the rights to use, copy, modify, merge,
# publish, distribute, sublicense, and/or sell copies of the Software,
# and to permit persons to whom the Software is furnished to do so,
# subject to the following conditions:
#
# The above copyright notice and this permission notice shall be
# included in all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
# EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF
# MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND
# NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE
# LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION
# OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION
# WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

init python:

    import math

    class BounceText(renpy.Displayable):
        def __init__(self, child, at=0.0, amp=10.0, period=1.0, **kwargs):
            super(BounceText, self).__init__(**kwargs)
            self.child = child
            self.at = at
            self.amp = amp
            self.period = period

        def render(self, width, height, st, at):
            cr = renpy.render(self.child, width, height, st, at)
            w, h = cr.get_size()

            render = renpy.Render(w, h)

            y = math.sin((st + self.at) * (2 * math.pi / self.period)) * self.amp

            render.blit(cr, (0, y))

            renpy.redraw(self, 0)

            return render

    def bounce_tag(tag, argument, contents):

        args = argument.split(",")

        amp = float(args[0]) if len(args) >= 1 and args[0] else 10.0
        period = float(args[1]) if len(args) >= 2 and args[1] else 1.0

        new_list = []

        index = 0

        for kind, text in contents:

            if kind == renpy.TEXT_TEXT:

                for char in text:

                    char_disp = BounceText(
                        Text(char),
                        at=index * 0.05,
                        amp=amp,
                        period=period
                    )

                    new_list.append((renpy.TEXT_DISPLAYABLE, char_disp))

                    index += 1

            else:
                new_list.append((kind, text))

        return new_list

    config.custom_text_tags["bounce"] = bounce_tag


    class WaveText(renpy.Displayable):
        def __init__(self, child, at=0.0, amp=5.0, period=1.0, **kwargs):
            super(WaveText, self).__init__(**kwargs)
            self.child = child
            self.at = at
            self.amp = amp
            self.period = period

        def render(self, width, height, st, at):
            cr = renpy.render(self.child, width, height, st, at)
            w, h = cr.get_size()

            render = renpy.Render(w, h)

            y = math.sin((st + self.at) * (2 * math.pi / self.period)) * self.amp

            render.blit(cr, (0, y))

            renpy.redraw(self, 0)

            return render

    def wave_tag(tag, argument, contents):

        args = argument.split(",")

        amp = float(args[0]) if len(args) >= 1 and args[0] else 5.0
        period = float(args[1]) if len(args) >= 2 and args[1] else 1.0

        new_list = []

        index = 0

        for kind, text in contents:

            if kind == renpy.TEXT_TEXT:

                for char in text:

                    char_disp = WaveText(
                        Text(char),
                        at=index * 0.05,
                        amp=amp,
                        period=period
                    )

                    new_list.append((renpy.TEXT_DISPLAYABLE, char_disp))

                    index += 1

            else:
                new_list.append((kind, text))

        return new_list

    config.custom_text_tags["wave"] = wave_tag


    class ShakeText(renpy.Displayable):
        def __init__(self, child, amount=2.0, **kwargs):
            super(ShakeText, self).__init__(**kwargs)
            self.child = child
            self.amount = amount

        def render(self, width, height, st, at):
            cr = renpy.render(self.child, width, height, st, at)
            w, h = cr.get_size()

            render = renpy.Render(w, h)

            x = renpy.random.randint(-int(self.amount), int(self.amount))
            y = renpy.random.randint(-int(self.amount), int(self.amount))

            render.blit(cr, (x, y))

            renpy.redraw(self, 0)

            return render

    def shake_tag(tag, argument, contents):

        amount = float(argument) if argument else 2.0

        new_list = []

        for kind, text in contents:

            if kind == renpy.TEXT_TEXT:

                for char in text:

                    char_disp = ShakeText(
                        Text(char),
                        amount=amount
                    )

                    new_list.append((renpy.TEXT_DISPLAYABLE, char_disp))

            else:
                new_list.append((kind, text))

        return new_list

    config.custom_text_tags["shake"] = shake_tag# TODO: Translation updated at 2026-07-29 08:15

# game/kinetic_text_tags.rpy:1
translate english 6c0c3176_1:

    # "Kinetic Text Tags Ren'Py Module 2021 Daniel Westfall <SoDaRa2595@gmail.com>"
    "Kinetic Text Tags Ren'Py Module 2021 Daniel Westfall <SoDaRa2595@gmail.com>"

# game/kinetic_text_tags.rpy:1
translate english 8689f4cd:

    # "http://twitter.com/sodara9 I'd appreciate being given credit if you do end up using it! :D Would really make my day to know I helped some people out! Really hope this can help the community create some really neat ways to spice up their dialogue! http://opensource.org/licenses/mit-license.php Github: https://github.com/SoDaRa/Kinetic-Text-Tags itch.io: https://wattson.itch.io/kinetic-text-tags Forum Post: https://lemmasoft.renai.us/forums/viewtopic.php?f=51&t=60527&sid=75b4eb1aa5212a33cbfe9b0354e5376b"
    "http://twitter.com/sodara9 I'd appreciate being given credit if you do end up using it! :D Would really make my day to know I helped some people out! Really hope this can help the community create some really neat ways to spice up their dialogue! http://opensource.org/licenses/mit-license.php Github: https://github.com/SoDaRa/Kinetic-Text-Tags itch.io: https://wattson.itch.io/kinetic-text-tags Forum Post: https://lemmasoft.renai.us/forums/viewtopic.php?f=51&t=60527&sid=75b4eb1aa5212a33cbfe9b0354e5376b"

