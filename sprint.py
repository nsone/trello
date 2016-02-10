#!/usr/bin/env python
"""
usage: sprint.py [<command>] [<args>...]

Commands:

    show    Show status of current sprint

"""

from docopt import docopt
from trello import Board
from ns1trellobase import NS1Base
import pprint


class Sprint(NS1Base):

    def show(self):
        board = Board(self.client, board_id=self.SPRINT_BOARD_ID)
        cards = board.open_cards()
        for c in cards:
            c.fetch(True)
            pprint.pprint(vars(c))

if __name__ == "__main__":

    args = docopt(__doc__)

    print args
    if args['<command>'] is None:
        args['<command>'] = 'show'

    t = Sprint()
    t.boot()

    if args['<command>'] == 'show':
        t.show()


# figure out old and new sprint numbers/dates

# MODE 1 outgoing/incoming
# outgoing sprint
## capture sprint board state to sqlite (end)
## archive everything in Done column
# incoming sprint
## change title to todays date
## right shift sprint roadmap, bring into current sprint
## capture tickets coming in from roadmap (so we can figure out which were added ad hoc after sprint start)

# (assumes manual things happen here to add sprint tickets)

# MODE 2 new sprint ready
## capture sprint board state to sqlite (start)

# reports
# outgoing
### num in each column
### num overdue
### avg age of open tickets
### num fires (label)
# incoming
### num incoming from sprint roadmaps
### total new (assuming some added manually from outside sprint roadmap)
