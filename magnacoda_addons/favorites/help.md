# Favorites help

<!--
These sections are added after *magnacoda*'s own in `help` (*magnacoda* reads this file through the help_text hook in plugin.py, each time help opens).
The format is the same as *magnacoda*'s magnacoda/data/help.md; its comment explains it. In short: "## name" starts a section (one word; it is the name shown in the pager's section list), "### Label" is a plain line, each paragraph is ONE long line, and a list item that starts with a term in backticks is a command, with its description on the next line indented 2 spaces.
A section name *magnacoda* already uses (overview, usage, commands, options, scan, examples) is skipped.
A test checks that every command this add-on adds is mentioned here.
-->

## favorites

### Favorites

Save the scans you run often, and start them again from the wizard.

To save one, answer yes to "Save this as a favorite?" at the end of the wizard, and give it a name. At the start of the wizard, type fav to list them, then pick one to run it again, or to change just the URL. If you change its settings, you're asked whether to update it.

- `favorites`
  List your favorites, numbered, with their commands. Enter a number to run that scan (it shows the command, says how long it will take, offers faster settings for this run, and asks first), or press Enter to go back.
- `favorites delete NUMBER`
  Delete one, after asking. You can give its name instead of its number (in quotes if it has spaces). Add --yes to skip the question.
- `fav / favs`
  Short forms of favorites: fav lists them, and fav delete NUMBER deletes one (favs works the same).

How many favorites are kept is set in the [favorites] section of preferences.ini (default 10, from 1 to 100). They are saved in favorites.md in *magnacoda*'s settings folder; you can also edit that file directly.
