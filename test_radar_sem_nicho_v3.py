import csv
import io
import json
from urllib.error import HTTPError
from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import radar_sem_nicho_v3 as radar

NOW='2026-11-17T12:00:00Z'

class MockAPI:
    key='test_nonsecret'
    search_calls=0
    other_calls=0
    limit_search=80
    limit_other=6000
    def __init__(self):
        self.search_params=[]
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
            self.search_params.append(dict(kw))
            assert 'q' not in kw and 'videoCategoryId' not in kw and 'topicId' not in kw
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
        if endpoint=='videoCategories':
            return {'items':[{'id':'27','snippet':{'title':'Education'}}]}
        raise ValueError(endpoint)

class TestRadar(unittest.TestCase):
    def test_topic_free_search_plan(self):
        api=MockAPI()
        found,audit=radar.discover(api,['US','CA'],'2026-10-27T00:00:00Z',
                    '2026-11-18T00:00:00Z',100,[],shards=2)
        self.assertEqual(api.search_calls,16)
        self.assertTrue(all(not any(k in x for k in ('q','topicId','videoCategoryId')) for x in api.search_params))
        self.assertEqual(len(audit),16)
        self.assertTrue(all(r['q_enviado']=='NAO' and r['categoria_filtrada']=='NAO' for r in audit))
        self.assertIn(api.ids[0],found['US'])

    def test_market_assignment_does_not_discard_other_declared_countries(self):
        with tempfile.TemporaryDirectory() as d:
            api=MockAPI()
            api.channels[0]['snippet']['country']='CA'  # E encontrado em busca US mesmo assim
            radar.main(['--countries','US','--start','2026-10-27','--end','2026-11-17',
                        '--output-dir',d,'--shards','1'],api=api)
            with (Path(d)/'canais_elegiveis_analisados.csv').open(encoding='utf-8-sig') as f:
                found=list(csv.DictReader(f))
            mixed=next(r for r in found if r['canal']=='Canal 0')
            self.assertEqual(mixed['pais_declarado'],'CA')
            self.assertEqual(mixed['qualificado'],'SIM')
            self.assertEqual(mixed['confianca_pais'],'BUSCA_REGIONAL_NAO_VERIFICADO')

    def test_categories_only_enriched_after_discovery(self):
        with tempfile.TemporaryDirectory() as d:
            api=MockAPI()
            orig=api.get
            def with_categories(endpoint,**kwargs):
                data=orig(endpoint,**kwargs)
                if endpoint=='videos':
                    for video in data['items']:
                        video['snippet']['categoryId']='27'
                return data
            api.get=with_categories
            radar.main(['--countries','US','--start','2026-10-27','--end','2026-11-17',
                        '--output-dir',d,'--shards','1'],api=api)
            with (Path(d)/'categorias_emergentes.csv').open(encoding='utf-8-sig') as f:
                cats=list(csv.DictReader(f))
            self.assertEqual(len(cats),1)
            self.assertEqual(cats[0]['categoria_youtube_nome'],'Education')
            self.assertEqual(cats[0]['videos_long'],'2')
            self.assertTrue(all('videoCategoryId' not in x for x in api.search_params))

    def test_key_file_loads_without_powershell_env(self):
        with tempfile.TemporaryDirectory() as d:
            secret = Path(d)/'youtube_api_key.txt'
            secret.write_text('  CHAVE_SIMULADA_123  \n', encoding='utf-8')
            with patch.object(radar, '__file__', str(Path(d)/'radar_sem_nicho_v3.py')):
                with patch.dict('os.environ', {'YOUTUBE_API_KEY': ''}):
                    self.assertEqual(radar.load_api_key(), 'CHAVE_SIMULADA_123')

    def test_key_file_wins_over_environment_variable(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d)/'youtube_api_key.txt').write_text('CHAVE_DO_ARQUIVO', encoding='utf-8')
            with patch.object(radar, '__file__', str(Path(d)/'radar_sem_nicho_v3.py')):
                with patch.dict('os.environ', {'YOUTUBE_API_KEY': 'CHAVE_DO_AMBIENTE'}):
                    self.assertEqual(radar.load_api_key(), 'CHAVE_DO_ARQUIVO')

    def test_placeholder_allows_environment_fallback(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d)/'youtube_api_key.txt').write_text('COLE_SUA_CHAVE_AQUI\n', encoding='utf-8')
            with patch.object(radar, '__file__', str(Path(d)/'radar_sem_nicho_v3.py')):
                with patch.dict('os.environ', {'YOUTUBE_API_KEY': 'CHAVE_BACKUP'}):
                    self.assertEqual(radar.load_api_key(), 'CHAVE_BACKUP')

    def test_missing_key_gives_actionable_message(self):
        with tempfile.TemporaryDirectory() as d:
            with patch.object(radar, '__file__', str(Path(d)/'radar_sem_nicho_v3.py')):
                with patch.dict('os.environ', {'YOUTUBE_API_KEY': ''}):
                    with self.assertRaises(SystemExit) as context:
                        radar.load_api_key()
            self.assertIn('youtube_api_key.txt', str(context.exception))
            self.assertNotIn('CHAVE_SIMULADA_123', str(context.exception))

    def test_key_file_rejects_multiple_lines(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d)/'youtube_api_key.txt').write_text('CHAVE1\nCHAVE2\n', encoding='utf-8')
            with patch.object(radar, '__file__', str(Path(d)/'radar_sem_nicho_v3.py')):
                with patch.dict('os.environ', {'YOUTUBE_API_KEY': ''}):
                    with self.assertRaises(SystemExit):
                        radar.load_api_key()

    def test_plan_only_requires_no_key_and_spends_no_quota(self):
        with patch.dict('os.environ',{'YOUTUBE_API_KEY':''}):
            self.assertIsNone(radar.main(['--plan-only','--countries','US','--shards','1']))

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
                        '--output-dir',str(path),'--shards','1'],api=api)
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
                        '--output-dir',str(out),'--shards','1',
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
                        '--output-dir',str(out),'--shards','1'],api=MockAPI())
            history=out/'historico_snapshots.csv'
            with history.open(encoding='utf-8-sig') as f:
                before=list(csv.DictReader(f))
            self.assertEqual(len(before),2)
            # Simula dia seguinte: fora da janela, ainda deve salvar snapshot de monitoramento.
            fake=MockAPI()
            fake.playlists['UP_0'].append(('2026-11-18T00:00:00Z','newerother1'))
            with patch.object(radar, 'datetime') as clock:
                clock.now.return_value=datetime(2026,11,18,12,tzinfo=timezone.utc)
                clock.fromisoformat.side_effect=datetime.fromisoformat
                clock.strptime=datetime.strptime
                radar.main(['--countries','US','--start','2026-11-18','--end','2026-11-18',
                            '--output-dir',str(out),'--shards','1'],api=fake)
            with history.open(encoding='utf-8-sig') as f:
                after=list(csv.DictReader(f))
            self.assertGreater(len(after),len(before))


    def test_daily_429_is_quota_and_not_retried(self):
        payload=json.dumps({"error":{"code":429,"message":"Quota exceeded for quota metric 'Search Queries' and limit 'Search Queries per day'","errors":[{"reason":"rateLimitExceeded"}]}}).encode("utf-8")
        def fail(*args,**kwargs):
            raise HTTPError('https://example.invalid',429,'limit',{},io.BytesIO(payload))
        with patch.object(radar.request,'urlopen',side_effect=fail) as opened:
            with patch.object(radar.time,'sleep') as paused:
                with self.assertRaises(radar.QuotaStop):
                    radar.YouTube('TEST_KEY',80,6000).get('search',part='snippet',type='video')
        self.assertEqual(opened.call_count,1)
        paused.assert_not_called()

    def test_quota_abort_preserves_previous_good_results(self):
        class Limited(MockAPI):
            def get(self,endpoint,**kw):
                if endpoint=='search':
                    self.search_calls+=1
                    raise radar.QuotaStop('COTA_DIARIA_SEARCH_ESGOTADA: Search Queries per day')
                return super().get(endpoint,**kw)
        with tempfile.TemporaryDirectory() as d:
            out=Path(d)
            report=out/'top50_longform_por_pais.csv'
            report.write_text('DADOS_ANTERIORES_NAO_MODIFICAR\n',encoding='utf-8')
            with self.assertRaises(SystemExit) as context:
                radar.main(['--countries','US','--start','2026-10-27','--end','2026-11-17',
                            '--output-dir',d,'--shards','1'],api=Limited())
            self.assertIn('PRESERVADOS',str(context.exception))
            self.assertEqual(report.read_text(encoding='utf-8'),'DADOS_ANTERIORES_NAO_MODIFICAR\n')
            self.assertEqual(json.loads((out/'status_coleta.json').read_text(encoding='utf-8'))['status'],
                             'INTERROMPIDA_QUOTA')
            with (out/'auditoria_busca_parcial_quota.csv').open(encoding='utf-8-sig') as f:
                records=list(csv.DictReader(f))
            self.assertEqual(len(records),1)
            self.assertFalse((out/'resumo_paises.csv').exists())



if __name__=='__main__':
    unittest.main()