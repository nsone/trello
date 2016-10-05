#!/usr/bin/env python
"""
usage: sprint.py [--db <db>] [--sprint-len <N>] [--last-sprint-id <date>] SPRINT_ID [<command>] [<args>...]

Options:
    --db <db>               Where to find the sqlite db.
    --sprint-len <N>        Set sprint length to N weeks
    --last-sprint-id <date> Override the last sprint id, useful when changing sprint lengths

Commands:
    which                          Show dates or previous, current, next sprints
    cards                          Update all known cards to latest due_dates, labels, etc
    show                           Show status of current sprint
    finish                         Finish the last sprint
    prepare                        Prepare for the current sprint
    start                          Start the current sprint
    report                         Show report on the given sprint ID
    backup                         Backup the sprint state database
    state START|FINISH             Show state of tickets in given sprint

"""

import datetime
import os
import shutil
import sqlite3

from bson import ObjectId
from docopt import docopt

from ns1trellobase import NS1Base
from trello import Board

# snapshot phases
START = 1
FINISH = 2

# labels
FIRE = 'Fire'
LABELS = [FIRE, 'Child', 'Ops', 'Frontend', 'Customer Fire', 'Backend', 'DevOps']

# columns
START_COL = 'New' # starting spot for a new card
TARGET_COL = 'Done'  # end target for a card

# report columns
COLS = [START_COL, 'Scoping', 'Blocked', 'In Progress', 'Review', 'Product Team Review', 'Deploy', TARGET_COL]
# punted if it didn't wind up in TARGET_COL
PUNT_COLS = COLS[:-1]
# any ticket that shows up midsprint in a column other than New
NIP_COLS = PUNT_COLS[1:]
# any outgoing column
OUT_COLS = COLS

# sprint length, in weeks
DEFAULT_SPRINT_LEN = 2

# set default due dates? set to None to disable
# otherwise, set to a time delta in the future
# default is last day of the sprint
DEFAULT_DUE_DATE = datetime.timedelta((7*DEFAULT_SPRINT_LEN)-1)

class Sprint(NS1Base):

    # roadmap https://trello.com/b/HNjbGF0O
    SPRINT_RM_BOARD_ID = '56746d07d270ded2a04eb52c'

    def __init__(self, dbname):
        super(Sprint, self).__init__()
        self._db = None
        self._db_name = dbname

        self.last_sprint_start = None
        self.next_sprint_start = None
        self.cur_sprint_start = None

        self.last_sprint_id = None
        self.next_sprint_id = None
        self.cur_sprint_id = None

        self.sprint_len = DEFAULT_SPRINT_LEN

        self.list_ids = {}
        self.list_names_by_id = {}

    def boot(self, sprint_id=None, last_sprint_id=None):
        super(Sprint, self).boot()
        self.determine_sprint(sprint_id, last_sprint_id)
        self._db = sqlite3.connect(self._db_name)
        self.create_tables()
        self.populate_tables()

    def create_tables(self):
        c = self._db.cursor()
        c.execute('''create table if not exists version (version text primary key)''')
        c.execute('''create table if not exists lists (list_id text primary key, name text)''')
        c.execute('''create table if not exists cards (card_id text primary key, create_date text, '''
                  '''sprint_add_date text, due_date text, labels text, name text)''')
        c.execute('''create table if not exists sprints (sprint_id text primary key, start_date text, '''
                  '''end_date text, started integer, prepared integer, finished integer)''')
        c.execute('''create table if not exists sprint_state (sprint_id text, list_id text, card_id text,'''
                  ''' snapshot_phase integer, from_roadmap integer)''')
        c.execute('''create unique index if not exists sprint_idx on sprint_state (sprint_id, list_id, '''
                  '''card_id, snapshot_phase)''')
        self._db.commit()
        c.close()

    def populate_tables(self):
        c = self._db.cursor()
        # version the db
        c.execute('insert or replace into version values (1)')
        # ensure we have all the lists
        board = Board(self.client, board_id=self.SPRINT_BOARD_ID)
        lists = board.open_lists()
        for l in lists:
            c.execute('''insert or replace into lists values (?, ?)''', (l.id, l.name))
            self.list_ids[l.name] = l.id
            self.list_names_by_id[l.id] = l.name
        # make sure this and next sprint are in sprints table
        c.execute('''insert or ignore into sprints values (?, ?, ?, 0, 0, 0)''',
                  (self.cur_sprint_id,
                   self.cur_sprint_start,
                   self.next_sprint_start -
                   datetime.timedelta(days=1)))
        c.execute('''insert or ignore into sprints values (?, ?, ?, 0, 0, 0)''',
                  (self.next_sprint_id,
                   self.next_sprint_start,
                   self.next_sprint_end))
        self._db.commit()
        c.close()

    def determine_sprint(self, sprint_id=None, last_sprint_id=None):
        if sprint_id:
            self.cur_sprint_start = datetime.datetime.strptime(sprint_id, "%Y-%m-%d")
        else:
            self.cur_sprint_start = datetime.datetime.today()
        if last_sprint_id:
            self.last_sprint_start = datetime.datetime.strptime(last_sprint_id, "%Y-%m-%d")
        else:
            self.last_sprint_start = self.cur_sprint_start - datetime.timedelta(weeks=self.sprint_len)

        self.next_sprint_start = self.cur_sprint_start + datetime.timedelta(weeks=self.sprint_len)
        self.next_sprint_end = self.next_sprint_start + datetime.timedelta(weeks=self.sprint_len) - datetime.timedelta(days=1)

        self.last_sprint_id = str(self.last_sprint_start.date())
        self.next_sprint_id = str(self.next_sprint_start.date())
        self.cur_sprint_id = str(self.cur_sprint_start.date())

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
        c.execute('''insert or replace into cards values (?, ?, ?, ?, ?, ?)''',
                  (card.id, create_date, datetime.datetime.today().isoformat(' '), card.due_date, ','.join(labels), card.name))
        c.close()

    def cards(self):
        c = self._db.cursor()
        sql = '''select card_id from cards'''
        r = c.execute(sql)
        cards = r.fetchall()
        for cid in cards:
            try:
                card = self.client.get_card(cid[0])
                print "working on %s" % (card)
            except:
                print "ERROR loading id %s, SKIPPING" % cid[0]
                self.write_card(card)
        c.close()

    def capture_sprint(self, sprint_id, snapshot_phase):
        board = Board(self.client, board_id=self.SPRINT_BOARD_ID)
        cards = board.open_cards()
        c = self._db.cursor()
        # make sure cards exist
        for card in cards:
            self.write_card(card)
            # write them to state
            c.execute('''insert or ignore into sprint_state values (?, ?, ?, ?, ?)''',
                      (sprint_id, card.list_id, card.id, snapshot_phase, 0))
        c.close()

    def get_sprint_flag(self, name, sprint_id):
        c = self._db.cursor()
        c.execute('''select %s from sprints where sprint_id=?''' % name, (sprint_id,))
        flag = c.fetchone()
        if flag is None:
            raise Exception('Unable to get %s from %s' % (name, sprint_id))
        c.close()
        return flag[0]

    def set_sprint_flag(self, name, sprint_id):
        c = self._db.cursor()
        c.execute('''update sprints set %s=1 where sprint_id=?''' % name, (sprint_id,))
        c.close()

    def ensure(self, name, sprint_id):
        flag = self.get_sprint_flag(name, sprint_id)
        if int(flag) != 1:
            raise Exception("Sprint %s has not yet been %s, aborting" % (sprint_id, name))

    def ensure_not(self, name, sprint_id):
        flag = self.get_sprint_flag(name, sprint_id)
        if int(flag) == 1:
            raise Exception("Sprint %s has already been %s, aborting" % (sprint_id, name))

    def finish_sprint(self):

        print "Finishing Sprint %s" % self.last_sprint_id

        self.ensure('prepared', self.last_sprint_id)
        self.ensure('started', self.last_sprint_id)
        self.ensure_not('finished', self.last_sprint_id)

        # outgoing sprint: snapshot_phase=2 (finish)
        try:
            self.capture_sprint(self.last_sprint_id, snapshot_phase=FINISH)
        except Exception as e:
            print "ROLLING BACK"
            self._db.rollback()
            raise e
        self.set_sprint_flag('finished', self.last_sprint_id)
        self._db.commit()

        # archive all cards in Done column
        board = Board(self.client, board_id=self.SPRINT_BOARD_ID)
        done_list = board.get_list(self.list_ids['Done'])
        done_list.archive_all_cards()
        # done_cards = done_list.list_cards()
        # for card in done_cards:
        #     if not card.closed:
        #         print "Closing Done ticket: %s" % card.name
        #         card.set_closed(True)


    def prep_sprint(self):
        # incoming sprint: snapshot_phase=1 (start), from_roadmap=1
        print "Preparing Sprint %s" % self.cur_sprint_id

        self.ensure_not('prepared', self.cur_sprint_id)

        ## change title to todays date
        board = Board(self.client, board_id=self.SPRINT_BOARD_ID)
        # no method for setting name, use client directly
        board.client.fetch_json(
            '/boards/' + board.id + '/name',
            http_method='PUT',
            post_args={'value': 'Engineering: Current Sprint %s' % self.cur_sprint_id, }, )

        ## right shift sprint roadmap, bring into current sprint
        rm_board = Board(self.client, board_id=self.SPRINT_RM_BOARD_ID)
        rm_lists = rm_board.open_lists()
        rm_list_map = {l.name: l.id for l in rm_lists}
        from_rm_cards = []
        for l in reversed(rm_lists):
            # leave any non S + N lists alone
            if not l.name.startswith('S +'):
                continue
            if l.name == 'S + 1':
                # capture this card list so we can mark from_roadmap correctly
                from_rm_cards = l.list_cards()
                # send to sprint
                board_id = self.SPRINT_BOARD_ID
                list_id = self.list_ids['New']
            else:
                # send to next col
                board_id = self.SPRINT_RM_BOARD_ID
                n_id = int(l.name[-1:])
                list_id = rm_list_map['S + %s' % str(n_id-1)]
            l.client.fetch_json(
                '/lists/' + l.id + '/moveAllCards',
                post_args={'idBoard': board_id, 'idList': list_id},
                http_method='POST')

        ## capture tickets coming in from roadmap (so we can figure out which were added ad hoc after sprint start)
        c = self._db.cursor()
        try:
            for card in from_rm_cards:
                card.fetch(True)
                # if we are doing default due dates, add now if it doesn't exist
                if card.due is None and DEFAULT_DUE_DATE:
                    card.set_due(self.cur_sprint_start + DEFAULT_DUE_DATE)
                self.write_card(card)
                # write them to state
                c.execute('''insert into sprint_state values (?, ?, ?, ?, ?)''',
                          (self.cur_sprint_id, card.list_id, card.id, 1, 1))
        except Exception as e:
            print "ROLLING BACK"
            self._db.rollback()
            raise e

        c.close()

        self.set_sprint_flag('prepared', self.cur_sprint_id)
        self._db.commit()

    def start_sprint(self):
        print "Starting Sprint %s" % self.cur_sprint_id

        self.ensure('prepared', self.cur_sprint_id)
        self.ensure_not('started', self.cur_sprint_id)
        # incoming sprint: snapshot_phase=1 (start), from_roadmap=0
        ## run after prep and after any manual tickets have been added, to capture sprint start
        ## capture sprint board state to sqlite (start)
        try:
            self.capture_sprint(self.cur_sprint_id, snapshot_phase=START)
        except Exception as e:
            print "ROLLING BACK"
            self._db.rollback()
            raise e

        self.set_sprint_flag('started', self.cur_sprint_id)
        self._db.commit()

    def backup(self):
        # send to s3
        shutil.copy(self._db_name, "%s.bak" % (self._db_name))

    def _report_count(self, sql, *args, **kwargs):
        c = self._db.cursor()
        r = c.execute(sql, *args, **kwargs)
        result = r.fetchall()
        c.close()
        return result[0][0]

    def _get_card_map(self, sprint_id, phase):
        c = self._db.cursor()
        sql = '''select card_id, list_id from sprint_state where snapshot_phase=? and sprint_id=?'''
        r = c.execute(sql, (phase, sprint_id, ))
        # list_id => [card_id, ...]
        map = {}
        for rec in r.fetchall():
            lname = self.list_names_by_id[rec[1]]
            if lname not in map:
                map[lname] = []
            map[lname].append(rec[0])
        c.close()
        return map

    def _array_marks(self, arr):
        if arr is None:
            return ''
        quoted = ['"%s"' % v for v in arr]
        return ','.join(quoted)

    def _pperc(self, part, total):
        if total == 0:
            return 'NaN'
        p = (float(part) / float(total)) * 100
        return "%s/%s%%" % (part, round(p, 2))

    def show_state(self, snapshot_phase):
        c = self._db.cursor()
        sql = '''select date(sprint_add_date), cards.name, labels, lists.name, due_date from sprint_state, cards,
                 lists where sprint_id=? and snapshot_phase=? and cards.card_id=sprint_state.card_id
                 and sprint_state.list_id=lists.list_id'''
        r = c.execute(sql, (self.cur_sprint_id, snapshot_phase))
        result = r.fetchall()
        for r in result:
            print r
        c.close()

    def _due_dates(self, sprint_id):
        c = self._db.cursor()
        sql = '''select date(due_date) from sprint_state, cards,
                 lists where sprint_id=? and snapshot_phase=? and cards.card_id=sprint_state.card_id
                 and sprint_state.list_id=lists.list_id'''
        r = c.execute(sql, (sprint_id, FINISH))
        result = r.fetchall()
        num_w_dates = 0
        num_overdue = 0
        last_day_of_sprint = self.next_sprint_start - datetime.timedelta(days=1)
        for r in result:
            if r[0] is None or r[0] == '':
                continue
            else:
                num_w_dates += 1
                dd = datetime.datetime.strptime(r[0], "%Y-%m-%d")
                if last_day_of_sprint > dd:
                    num_overdue += 1
        c.close()
        return (num_w_dates, num_overdue)

    def report(self, sprint_id):
        print "Sprint Report %s (compared to previous %s)" % (sprint_id, self.last_sprint_id)

        assert(sprint_id != self.last_sprint_id)

        # get a list of card ids from all the lists from last sprint finish, so we can see how they changed
        # (or not) to this sprint
        last_finish_map = self._get_card_map(self.last_sprint_id, FINISH)

        # for l in self.list_ids:
        #     print l
        #     print last_finish_map[self.list_ids[l]]

        sql = '''select count(*) from sprint_state where sprint_id=? and snapshot_phase=1'''
        total_at_start = self._report_count(sql, (sprint_id, ))
        sql = '''select count(*) from sprint_state where sprint_id=? and snapshot_phase=2'''
        total_at_finish = self._report_count(sql, (sprint_id, ))

        # incoming: new to this sprint
        print "INCOMING"
        print " -- NEW"

        ### num incoming from sprint roadmaps (excluding cards carried over form last sprint)
        sql = '''select count(*) from sprint_state, cards where sprint_id=? and snapshot_phase=1 and
                 from_roadmap=1 and list_id=? and cards.card_id=sprint_state.card_id
                 and sprint_state.card_id not in (%s)''' % (self._array_marks(last_finish_map.get('New', None)))
        print "Incoming From Sprint Roadmap"
        incoming_roadmap = self._report_count(sql, (sprint_id, self.list_ids['New']))
        print incoming_roadmap

        ### num added to New column after Prep (after incoming from roadmap) but before Start
        sql = '''select count(*) from sprint_state, cards where sprint_id=? and snapshot_phase=1 and
                 from_roadmap=0 and list_id=? and cards.card_id=sprint_state.card_id
                 and sprint_state.card_id not in (%s)''' % (self._array_marks(last_finish_map.get('New', None)))
        print "Additional Incoming At Sprint Planning Time"
        incoming_adhoc = self._report_count(sql, (sprint_id, self.list_ids['New']))
        print incoming_adhoc

        ### total new at start
        sql = '''select count(*) from sprint_state, cards where sprint_id=? and snapshot_phase=1 and
                 list_id=? and cards.card_id=sprint_state.card_id
                 and sprint_state.card_id not in (%s)''' % (self._array_marks(last_finish_map.get('New', None)))
        total_incoming = self._report_count(sql, (sprint_id, self.list_ids['New']))
        assert(total_incoming == (incoming_adhoc + incoming_roadmap))
        print "TOTAL INCOMING NEW: %s" % (self._pperc(total_incoming, total_at_start))

        # incoming: punted/existed in last sprint
        print " -- PUNTED/CARRYOVER"

        ### num punted from last sprint in various columns
        punt_counts = 0
        for pc in PUNT_COLS:
            if pc not in last_finish_map:
                continue
            sql = '''select count(*) from sprint_state where sprint_id=? and snapshot_phase=1 and
                     list_id=? and sprint_state.card_id in (%s)''' % (self._array_marks(last_finish_map[pc]))
            print "Punted From Last Sprint: %s" % pc
            rc = self._report_count(sql, (sprint_id, self.list_ids[pc]))
            punt_counts += int(rc)
            print rc

        print "TOTAL INCOMING PUNTED: %s" % (self._pperc(punt_counts, total_at_start))

        # incoming: dropped into a column ad hoc, skipping New
        print " -- NEW, BUT ALREADY IN PROGRESS"

        ### num added to a column this sprint which wasn't in last sprint and skipped new
        nip_counts = 0
        for pc in NIP_COLS:
            if pc not in last_finish_map:
                continue
            sql = '''select count(*) from sprint_state where sprint_id=? and snapshot_phase=1 and
                     list_id=? and sprint_state.card_id not in (%s)''' % (self._array_marks(last_finish_map[pc]))
            print "New In Progress This Sprint: %s" % pc
            rc = self._report_count(sql, (sprint_id, self.list_ids[pc]))
            nip_counts += int(rc)
            print rc

        print "TOTAL INCOMING IN PROGRESS: %s" % (self._pperc(nip_counts, total_at_start))

        print "TOTAL AT SPRINT START: %s" % (total_at_start)
        assert(total_incoming + punt_counts + nip_counts == total_at_start)

        print "=-=-=-=-=-=-=-=-=-="
        print "OUTGOING"
        print " -- TOTALS"

        # outgoing
        ### num in each column
        out_counts = 0
        for pc in OUT_COLS:
            sql = '''select count(*) from sprint_state where sprint_id=? and snapshot_phase=2 and list_id=?'''
            print "Outgoing: %s" % pc
            rc = self._report_count(sql, (sprint_id, self.list_ids[pc]))
            out_counts += int(rc)
            if pc == TARGET_COL:
                done_count = int(rc)
            print self._pperc(rc, total_at_finish)

        print "TOTAL OUTGOING: %s" % (out_counts)
        assert(total_at_finish == out_counts)

        ### num per label
        for l in LABELS:
            sql = '''select count(*) from sprint_state, cards where sprint_id=? and snapshot_phase=2
                     and cards.card_id=sprint_state.card_id and instr(cards.labels, "%s")''' % l
            num_label = self._report_count(sql, (sprint_id, ))
            print "TOTAL LABEL %s: %s" % (l, self._pperc(num_label, total_at_finish))

        ### in to out ratio
        print "INCOMING to DONE RATIO: %s:%s/%f" % (total_incoming,
                                                    done_count,
                                                    float(total_incoming)/done_count)

        ### num overdue
        ### num w due dates
        (num_w_dates, num_overdue) = self._due_dates(sprint_id)
        print "OUTGOING WITH DUEDATES: %s" % (self._pperc(num_w_dates, out_counts))
        print "OUTGOING OVERDUE: %s" % (self._pperc(num_overdue, out_counts))

        ### now many NEW fires this sprint?

        ### avg overdue age of overdue tickets
        ### avg age of open tickets
        ### avg length in sprint



if __name__ == "__main__":

    args = docopt(__doc__)
    # print args

    if args['<command>'] is None:
        args['<command>'] = 'which'

    if args['--db'] is None:
        args['--db'] = os.getenv('HOME') + '/.ns1sprint.db'

    t = Sprint(args['--db'])

    if args['--sprint-len']:
        t.sprint_len = args['--sprint-len']

    t.boot(args['SPRINT_ID'], args['--last-sprint-id'])

    if args['<command>'] == 'which':
        print "Current Sprint is: %s, Next Sprint is %s, Next Sprint End is %s, Last Sprint is: %s, Sprint Length: %s" % \
              (t.cur_sprint_id, t.next_sprint_id, t.next_sprint_end, t.last_sprint_id, t.sprint_len)
    elif args['<command>'] == 'show':
        t.show()
    elif args['<command>'] == 'finish':
        t.finish_sprint()
    elif args['<command>'] == 'prepare':
        t.prep_sprint()
    elif args['<command>'] == 'start':
        t.start_sprint()
    elif args['<command>'] == 'backup':
        t.backup()
    elif args['<command>'] == 'cards':
        t.cards()
    elif args['<command>'] == 'state':
        if len(args['<args>']) == 0:
            raise Exception('state requires a snapshot phase (default START)')
        if args['<args>'][0] == 'finish':
            phase = FINISH
        else:
            phase = START
        t.show_state(phase)
    elif args['<command>'] == 'report':
        t.report(args['SPRINT_ID'])
    else:
        print "unknown command: %s" % args['<command>']


