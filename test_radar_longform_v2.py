import csv
from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import radar_longform_v2 as radar

NOW='2026-11-17T12:00:00Z'

class MockAPI:
    key='test_nonsecret'
    search_calls=0
    other_calls=0
    limit_search=80
    limit_other=6000
    def __init__(self):
        self.ids=['UC'+'A'*22,'UC'+'B'*22,'UC'+'C'*22]
        self.channels=[]
        for i,cid in enumerate(self.ids):
            self.channels.append({'id':cid,'snippet':{'title':f'Canal {i}', 'publishedAt':'2022-01-01T00:00:00Z','country':'US'},
              'statistics':{'viewCount':'10000','subscriberCount':'500','videoCount':'3'},
              'contentDetails':{'relatedPlaylists':{'uploads':'UP_'+str(i)}}})
        self.playlists={
          'UP_0':[('2026-11-12T00:00:00Z','videoaaaaaa'),('2026-11-08T00:00:00Z','videobbbbbb'),('2026-10-30T00:00:00Z','videocccccc')],
          'UP_1':[('2026-11-10T00:00:00Z','videodddddd')],
          'UP_2':[('2026-11-10T00:00:00Z','videoeeeeee'),('2026-09-10T00:00:00Z','videoffffff')]}
        self.videos={
          'videoaaaaaa':(500000,'PT1M30S','Viral Short'),
          'videobbbbbb':(15000,'PT12M30S','Video Long'),
          'videocccccc':(10000,'PT6M30S','Outro Long'),
          'videodddddd':(1000000,'PT45S','Only Short'),
        }
    def get(self, endpoint, **kw):
        if endpoint == 'search':
            self.search_calls+=1
            return {'items':[{'snippet':{'channelId':c}} for c in self.ids]}
        self.other_calls+=1
        if endpoint=='channels':
            return {'items':[x for x in self.channels if x['id'] in kw['id'].split(',')]}
        if endpoint=='playlistItems':
            return {'items':[{'contentDetails':{'videoPublishedAt':d,'videoId':v}} for d,v in self.playlists[kw['playlistId']]]}
        if endpoint=='videos':
            return {'items':[{'id':v,'snippet':{'title':self.videos[v][2],'publishedAt':'2026-11-16T00:00:00Z'},
                              'statistics':{'viewCount':self.videos[v][0],'likeCount':100,'commentCount':4},
                              'contentDetails':{'duration':self.videos[v][1]}}
                             for v in kw['id'].split(',')]}
        raise ValueError(endpoint)

class TestRadar(unittest.TestCase):
    def test_duration(self):
        self.assertEqual(radar.duration_seconds('PT1H2M3S'),3723)
        self.assertEqual(radar.duration_seconds('PT3M'),180)
        self.assertEqual(radar.duration_seconds('P1DT2H'),93600)
        self.assertIsNone(radar.duration_seconds('oops'))

    def test_3minute_short_boundary(self):
        base={'id':'video123456','snippet':{'title':'foo','publishedAt':NOW},'statistics':{'viewCount':'10'}}
        channel={'id':'UC'+'A'*22,'snippet':{'title':'A','country':'US'}}
        for sec,expected in [(180,'ATE_3M_POSSIVEL_SHORT'),(181,'LONG_3A8'),
                             (479,'LONG_3A8'),(480,'LONG_8A20'),(1200,'LONG_20MAIS')]:
            video=dict(base,contentDetails={'duration':f'PT{sec}S'})
            self.assertEqual(radar.classify_video(video,channel,'US',radar.iso_date(NOW))['faixa_duracao'],expected)

    def test_end_to_end_mixed_channel_retained(self):
        with tempfile.TemporaryDirectory() as dir:
            path=Path(dir)
            api=MockAPI()
            radar.main(['--countries','US','--start','2026-10-27','--end','2026-11-17',
                        '--output-dir',str(path),'--terms-per-country','1'],api=api)
            with (path/'top50_longform_por_pais.csv').open(encoding='utf-8-sig') as f:
                rows=list(csv.DictReader(f))
            self.assertEqual(len(rows),1)
            self.assertEqual(rows[0]['canal'],'Canal 0')
            self.assertEqual(rows[0]['videos_long_total'],'2')
            self.assertEqual(rows[0]['videos_ate_3min_indefinidos'],'1')
            self.assertEqual(rows[0]['views_long_total'],'25000')
            self.assertEqual(rows[0]['views_ate3'],'500000')
            self.assertEqual(rows[0]['categoria_oportunidade'],'MISTO_PROMISSOR')
            with (path/'auditoria_candidatos.csv').open(encoding='utf-8-sig') as f:
                audit=list(csv.DictReader(f))
            self.assertIn('VIDEO_PUBLICO_ANTIGO',{r['estado'] for r in audit})
            with (path/'resumo_paises.csv').open(encoding='utf-8-sig') as f:
                summ=list(csv.DictReader(f))
            self.assertEqual(summ[0]['posicoes_pendentes'],'49')

    def test_manual_override_and_preserves_review_csv(self):
        with tempfile.TemporaryDirectory() as d:
            out=Path(d)
            # Um video curto horizontal verificado manualmente integra longform.
            override=out/'manual.csv'
            with override.open('w',encoding='utf-8',newline='') as f:
                writer=csv.DictWriter(f,fieldnames=['video_id','tipo_confirmado'])
                writer.writeheader()
                writer.writerow({'video_id':'videoaaaaaa','tipo_confirmado':'LONG'})
            api=MockAPI()
            radar.main(['--countries','US','--start','2026-10-27','--end','2026-11-17',
                        '--output-dir',str(out),'--terms-per-country','1',
                        '--manual-csv',str(override)],api=api)
            with (out/'canais_elegiveis_analisados.csv').open(encoding='utf-8-sig') as f:
                rows=list(csv.DictReader(f))
            mixed=[r for r in rows if r['canal']=='Canal 0'][0]
            self.assertEqual(mixed['videos_long_total'],'3')
            self.assertEqual(mixed['videos_ate_3min_indefinidos'],'0')
            self.assertEqual(mixed['videos_long_ate3_confirmados'],'1')
            with (out/'revisao_short_manual.csv').open(encoding='utf-8-sig') as f:
                pending=list(csv.DictReader(f))
            self.assertEqual([r['tipo_confirmado'] for r in pending if r['video_id']=='videoaaaaaa'],['LONG'])

    def test_seeded_history_and_watchlist_recheck(self):
        with tempfile.TemporaryDirectory() as d:
            out=Path(d)
            radar.main(['--countries','US','--start','2026-10-27','--end','2026-11-17',
                        '--output-dir',str(out),'--terms-per-country','1'],api=MockAPI())
            history=out/'historico_snapshots.csv'
            with history.open(encoding='utf-8-sig') as f:
                before=list(csv.DictReader(f))
            self.assertEqual(len(before),2)
            # Simula dia seguinte: fora da janela, ainda deve salvar snapshot de monitoramento.
            fake=MockAPI()
            fake.playlists['UP_0'].append(('2026-11-18T00:00:00Z','newerother1'))
            with patch.object(radar, 'datetime') as clock:
                clock.now.return_value=datetime(2026,11,18,12,tzinfo=timezone.utc)
                clock.strptime=datetime.strptime
                radar.main(['--countries','US','--start','2026-11-18','--end','2026-11-18',
                            '--output-dir',str(out),'--terms-per-country','1'],api=fake)
            with history.open(encoding='utf-8-sig') as f:
                after=list(csv.DictReader(f))
            self.assertGreater(len(after),len(before))


if __name__=='__main__':
    unittest.main()