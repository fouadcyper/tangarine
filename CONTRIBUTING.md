# Contributing to QuickConvert

Thank you for helping improve QuickConvert.

1. Fork the repository and create a focused branch.
2. Keep the radial GNOME Wayland overlay as the primary interaction.
3. Do not introduce an X11 or Xwayland requirement.
4. Keep conversion commands as argument lists and never interpolate untrusted
   filenames into a shell command.
5. Leave source files untouched and never persist signing passwords.
6. Run `PYTHONPATH=. python3 -m unittest discover -s tests -v`.
7. Open a pull request describing the user-visible change and how it was tested.

GNOME Shell drag behavior must be tested in a real Wayland session. A unit test
or an extension marked active is not sufficient proof that live Nautilus drag
activation works.
