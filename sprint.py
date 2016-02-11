#!/usr/bin/env python
"""
usage: sprint.py [--db <db>] [<command>] [<args>...]

Options:
    --db <db>    Where to find the sqlite db.

Commands:
    show    Show status of current sprint

"""

import datetime
import os
import sqlite3

from docopt import docopt

from ns1trellobase import NS1Base
from trello import Board


class Sprint(NS1Base):

    def __init__(self, dbname):
        super(Sprint, self).__init__()
        self._db_name = dbname
        self.today = None
        self.next_tue = None
        self.last_tue = None

    def boot(self):
        super(Sprint, self).boot()
        self.determine_sprint()
        self._db = sqlite3.connect(self._db_name)
        self.create_tables()
        self.populate_tables()

    def create_tables(self):
        c = self._db.cursor()
        c.execute('''create table if not exists lists (list_id text pimary key, name text)''')
        c.execute('''create table if not exists cards (card_id text primary key, add_date text, due_date text,'''
                  '''labels text, title text)''')
        c.execute('''create table if not exists sprints (sprint_id text primary key, start_date text, end_date text)''')
        c.execute('''create table if not exists sprint_state (sprint_id text, list_id text, card_id text,'''
                  ''' snapshot_time integer, from_roadmap integer)''')
        c.execute('''create unique index if not exists sprint_idx on sprint_state (sprint_id, list_id, '''
                  '''card_id, snapshot_time)''')
        self._db.commit()
        c.close()

    def populate_tables(self):
        c = self._db.cursor()
        c.execute('''select count(*) from lists''')
        lc = c.fetchone()
        if (lc[0] == 0):
            # populate the lists
            board = Board(self.client, board_id=self.SPRINT_BOARD_ID)
            lists = board.open_lists()
            for l in lists:
                c.execute('''insert into lists values (?, ?)''', (l.id, l.name))
        # make sure this and next sprint are in sprints table
        c.execute('''insert or replace into sprints values (?, ?, ?)''', (self.last_tue,
                                                                          self.last_tue,
                                                                          self.next_tue-datetime.timedelta(days=1)))
        c.execute('''insert or replace into sprints values (?, ?, ?)''', (self.next_tue,
                                                                          self.next_tue,
                                                                          self.next_weekday(self.next_tue, 0)))
        self._db.commit()
        c.close()

    # http://stackoverflow.com/questions/6558535/python-find-the-date-for-the-first-monday-after-a-given-a-date
    def next_weekday(self, d, weekday):
        days_ahead = weekday - d.weekday()
        if days_ahead <= 0:  # Target day already happened this week
            days_ahead += 7
        return d + datetime.timedelta(days_ahead)

    def determine_sprint(self):
        self.today = datetime.date.today()
        self.next_tue = self.next_weekday(self.today, 1)
        self.last_tue = self.next_weekday(self.today - datetime.timedelta(days=8), 1)

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
    # print args

    if args['<command>'] is None:
        args['<command>'] = 'show'

    if args['--db'] is None:
        args['--db'] = os.getenv('HOME') + '/.ns1sprint.db'

    t = Sprint(args['--db'])
    t.boot()

    if args['<command>'] == 'which':
        print "Today is: %s, Current Tue is: %s, Next Tue is: %s" % (t.today, t.last_tue, t.next_tue)
    elif args['<command>'] == 'show':
        t.show()
    elif args['<command>'] == 'finish':
        t.finish()
    elif args['<command>'] == 'start':
        t.start()


