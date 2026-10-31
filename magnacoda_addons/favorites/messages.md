# Favorites: on-screen wording

<!--
Everything the favorites command says on screen comes from this file, so the wording can be changed here without touching the code. It is read each time a message is shown.

HOW IT IS READ
  * Anything inside an HTML comment, like this one, is a note to editors. It is never shown.
  * "## name" starts a message; the code asks for it by that name. Don't rename or remove one (a test checks that every name the code uses is here).
  * The text below the name, up to the next "## ", is the message. Write each paragraph as ONE long line; it is wrapped to the terminal width when shown. A blank line between paragraphs is kept.
  * Words in braces, like {count}, are filled in by the program. Keep each one the message already has; a test checks them. To show a real brace, write {{ or }}.
-->

## favorites-empty

No favorites yet. At the end of the wizard, answer yes to "Save this as a favorite?"

## favorites-heading

Favorites ({count} of {limit}):

## pick-prompt

Type a number to run that scan, or help for more

## pick-again

type one of the numbers above (1 to {count}), or help, or press Enter (back).

## run-confirm

Run '{name}' now?

## delete-confirm

Delete favorite {number}, '{name}'?

## delete-done

Deleted '{name}' ({left}).

## delete-done-left

{count} left

## delete-done-none

no favorites left

## delete-cancelled

Not deleted.

## delete-unknown

There is no favorite '{which}'. Type `favorites` to see the list.

## save-failed

Could not save favorites.md: {reason}
