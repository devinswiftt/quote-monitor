import unittest
from hk_quote.participation import Participation,summarize


class ParticipationTests(unittest.TestCase):
    def build(self, extra=False):
        p=Participation()
        for second in range(90,111):
            rows=[dict(id='1001',name='甲',position=1),dict(id='1002',name='甲',position=2)]
            if second%2==0:rows.append(dict(id='2001',name='乙',position=1))
            e=dict(kind='broker',source='push',code='HK.02065',bid=rows,ask=[])
            p.observe(second,e)
            if extra:
                for j in range(1,10):p.observe(second+j/10,e)
        return p.analyze(dict(code='HK.02065'),100)

    def test_fixed_sampling_and_multiple_ids_grouped(self):
        result=self.build()
        self.assertEqual(result['valid_samples'],21)
        self.assertEqual(result['bid'][0]['name'],'甲')
        self.assertEqual(result['bid'][0]['presence_ratio'],1)
        self.assertEqual(result['bid'][0]['mean_queue_entries'],1)
        self.assertEqual(result['bid'][0]['ids'],['1001'])
        self.assertEqual(result['bid'][1]['present_samples'],11)

    def test_duplicate_pushes_do_not_inflate_frequency(self):
        self.assertEqual(self.build(),self.build(extra=True))

    def test_missing_data_is_not_a_zero_presence_sample(self):
        p=Participation();r=p.analyze(dict(code='HK.02065'),100)
        self.assertEqual(r['status'],'unavailable')
        self.assertEqual(r['valid_samples'],0)

    def test_summary_counts_once_per_alert_per_side(self):
        a=dict(code='HK.02065',signal='BUY',participation=self.build())
        rows=summarize([a,a]);self.assertEqual(rows[0]['alerts'],2)

class ChangeTests(unittest.TestCase):
    def build(self, baseline=True):
        p=Participation()
        for second in range(30 if baseline else 90,111):
            rows=[dict(id='1001',name='常驻',position=1),dict(id='9000',name='远档',position=2)]
            if second<90:rows.append(dict(id='2001',name='退出',position=1))
            else:rows.append(dict(id='3001',name='新增',position=1))
            p.observe(second,dict(kind='broker',source='push',code='HK.02065',bid=rows,ask=[]))
        return p.analyze(dict(code='HK.02065',signal='BUY'),100)

    def test_baseline_excludes_event_and_residents_do_not_rank_as_changes(self):
        r=self.build()
        self.assertEqual(r['baseline']['valid_samples'],60)
        self.assertEqual({v['name'] for v in r['changes']},{'新增','退出'})
        self.assertEqual({v['name'] for v in r['bid']},{'新增','常驻'})
        self.assertTrue(all('9000' not in v['ids'] for v in r['bid']))
        self.assertEqual(next(v for v in r['changes'] if v['name']=='退出')['change'],'退出最优档')

    def test_insufficient_baseline_is_not_evidence_of_a_new_broker(self):
        r=self.build(baseline=False)
        self.assertFalse(r['baseline']['sufficient'])
        self.assertEqual(r['changes'],[])
        self.assertTrue(r['bid'])

    def test_legacy_all_level_profiles_are_excluded(self):
        a=dict(code='HK.02065',signal='BUY',participation=dict(status='ready',bid=[dict(name='旧',ids=['1'])],ask=[]))
        self.assertEqual(summarize([a]),[])

    def test_exits_count_as_changes_without_being_present(self):
        a=dict(code='HK.02065',signal='BUY',participation=self.build())
        rows={r['name']:r for r in summarize([a])}
        self.assertEqual(rows['退出']['alerts'],0)
        self.assertEqual(rows['退出']['changed_alerts'],1)
        self.assertEqual(rows['常驻']['changed_alerts'],0)
        self.assertEqual(rows['新增']['eligible_alerts'],1)
