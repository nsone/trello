#!/usr/bin/env python
"""
usage: sprint.py [<command>] [<args>...]

Commands:

    show    Show status of current sprint

"""

from docopt import docopt
from trello import Board
from ns1trellobase import NS1Base
import datetime


class Sprint(NS1Base):

    # http://stackoverflow.com/questions/6558535/python-find-the-date-for-the-first-monday-after-a-given-a-date
    def next_weekday(self, d, weekday):
        days_ahead = weekday - d.weekday()
        if days_ahead <= 0:  # Target day already happened this week
            days_ahead += 7
        return d + datetime.timedelta(days_ahead)

    def determine_sprint(self):
        today = datetime.date.today()
        next_tue = self.next_weekday(today, 1)
        last_tue = self.next_weekday(today - datetime.timedelta(days=8), 1)
        print "Today is: %s, Current Tue is: %s, Next Tue is: %s" % (today, last_tue, next_tue)

    def show(self):
        board = Board(self.client, board_id=self.SPRINT_BOARD_ID)
        lists = board.open_lists()
        list_map = {}
        for l in lists:
            cards = l.list_cards()
            list_map[l.name] = [c.name for c in cards]
        print list_map

    def start(self):
        # MODE 1 outgoing/incoming
        # outgoing sprint
        ## capture sprint board state to sqlite (end)
        ## archive everything in Done column
        # incoming sprint
        ## change title to todays date
        ## right shift sprint roadmap, bring into current sprint
        ## capture tickets coming in from roadmap (so we can figure out which were added ad hoc after sprint start)

        pass

    def finish(self):
        # MODE 2 new sprint ready
        ## capture sprint board state to sqlite (start)
        pass

    def report(self):
        # reports
        # outgoing
        ### num in each column
        ### num overdue
        ### avg age of open tickets
        ### num fires (label)
        # incoming
        ### num incoming from sprint roadmaps
        ### total new (assuming some added manually from outside sprint roadmap)
        pass

if __name__ == "__main__":

    args = docopt(__doc__)

    if args['<command>'] is None:
        args['<command>'] = 'show'

    t = Sprint()
    t.boot()

    if args['<command>'] == 'which':
        t.determine_sprint()
    elif args['<command>'] == 'show':
        t.show()
    elif args['<command>'] == 'finish':
        t.finish()
    elif args['<command>'] == 'start':
        t.start()


