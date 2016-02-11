#!/usr/bin/env python
"""
usage: sprint.py [--db <db>] [--pretend <date>] [<command>] [<args>...]

Options:
    --db <db>         Where to find the sqlite db.
    --pretend <date>  Pretend today is date

Commands:
    show    Show status of current sprint

"""

import datetime
import os
import sqlite3
import pprint

from bson import ObjectId
from docopt import docopt

from ns1trellobase import NS1Base
from trello import Board


class Sprint(NS1Base):

    def __init__(self, dbname):
        super(Sprint, self).__init__()
        self._db = None
        self._db_name = dbname
        self.today = None
        self.last_sprint_start = None
        self.next_sprint_start = None
        self.cur_sprint_start = None
        self.date_pretend = None

    def boot(self):
        super(Sprint, self).boot()
        self.determine_sprint(self.date_pretend)
        self._db = sqlite3.connect(self._db_name)
        self.create_tables()
        self.populate_tables()

    def create_tables(self):
        c = self._db.cursor()
        c.execute('''create table if not exists lists (list_id text pimary key, name text)''')
        c.execute('''create table if not exists cards (card_id text primary key, create_date text, '''
                  '''sprint_add_date text, due_date text, labels text, name text)''')
        c.execute('''create table if not exists sprints (sprint_id text primary key, start_date text, end_date text)''')
        c.execute('''create table if not exists sprint_state (sprint_id text, list_id text, card_id text,'''
                  ''' snapshot_phase integer, from_roadmap integer)''')
        c.execute('''create unique index if not exists sprint_idx on sprint_state (sprint_id, list_id, '''
                  '''card_id, snapshot_phase)''')
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
        c.execute('''insert or ignore into sprints values (?, ?, ?)''', (self.cur_sprint_start.date(),
                                                                         self.cur_sprint_start,
                                                                         self.next_sprint_start -
                                                                         datetime.timedelta(days=1)))
        c.execute('''insert or ignore into sprints values (?, ?, ?)''', (self.next_sprint_start.date(),
                                                                         self.next_sprint_start,
                                                                         self.next_weekday(self.next_sprint_start, 0)))
        self._db.commit()
        c.close()

    # http://stackoverflow.com/questions/6558535/python-find-the-date-for-the-first-monday-after-a-given-a-date
    def next_weekday(self, d, weekday):
        days_ahead = weekday - d.weekday()
        if days_ahead <= 0:  # Target day already happened this week
            days_ahead += 7
        return d + datetime.timedelta(days_ahead)

    def determine_sprint(self, override=None):
        if override:
            self.today = datetime.datetime.strptime(override, "%Y-%m-%d")
        else:
            self.today = datetime.datetime.today()
        if self.today.weekday() == 1:
            # today is a tue
            self.cur_sprint_start = self.today
        else:
            self.cur_sprint_start = self.next_weekday(self.today - datetime.timedelta(days=8), 1)

        self.next_sprint_start = self.next_weekday(self.today, 1)
        self.last_sprint_start = self.next_weekday(self.cur_sprint_start - datetime.timedelta(days=8), 1)

    def show(self):
        board = Board(self.client, board_id=self.SPRINT_BOARD_ID)
        lists = board.open_lists()
        list_map = {}
        for l in lists:
            cards = l.list_cards()
            list_map[l.name] = [c.name for c in cards]
        print list_map

    def write_card(self, card):
        card.fetch()
        # pprint.pprint(vars(card))
        c = self._db.cursor()
        labels = [l.name for l in card.labels]
        create_date = ObjectId(card.id).generation_time
        c.execute('''insert or ignore into cards values (?, ?, ?, ?, ?, ?)''',
                  (card.id, create_date, self.today.isoformat(' '), card.due_date, ','.join(labels), card.name))
        # self._db.commit()
        c.close()

    def capture_sprint(self, snapshot_phase):
        board = Board(self.client, board_id=self.SPRINT_BOARD_ID)
        cards = board.open_cards()
        c = self._db.cursor()
        # make sure cards exist
        for c in cards:
            self.write_card(c)
            # write them to state
            c.execute('''insert into sprint_state values (?, ?, ?, ?, ?)''',
                      (self.cur_sprint_start, ))

        self._db.commit()
        c.close()


    def finish_sprint(self):
        # outgoing sprint: snapshot_phase=2 (finish)
        ## capture sprint board state to sqlite (end)
        self.capture_sprint(snapshot_phase=2)
        ## archive everything in Done column

        pass

    def prep_sprint(self):
        # incoming sprint: snapshot_phase=1 (start), from_roadmap=1
        ## change title to todays date
        ## right shift sprint roadmap, bring into current sprint
        ## capture tickets coming in from roadmap (so we can figure out which were added ad hoc after sprint start)
        pass

    def start_sprint(self):
        # incoming sprint: snapshot_phase=1 (start), from_roadmap=0
        ## run after prep and after any manual tickets have been added, to capture sprint start
        ## capture sprint board state to sqlite (start)
        self.capture_sprint(snapshot_phase=1)
        pass

    def backup(self):
        # send to s3
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
    if args['--pretend']:
        t.date_pretend = args['--pretend']
    t.boot()

    if args['<command>'] == 'which':
        print "Today is: %s, Current Sprint is: %s, Next Sprint is %s, Last Sprint is: %s" % \
              (t.today, t.cur_sprint_start, t.next_sprint_start, t.last_sprint_start)
    elif args['<command>'] == 'show':
        t.show()
    elif args['<command>'] == 'finish':
        t.finish_sprint()
    elif args['<command>'] == 'prep':
        t.prep_sprint()
    elif args['<command>'] == 'start':
        t.start_sprint()
    elif args['<command>'] == 'backup':
        t.backup()


