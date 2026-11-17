# Dark Channels Radar — pesquisa de canais novos no YouTube

**Versão atual: Radar v3.1, SEM FILTRO POR TEMA.** O assunto do canal é uma conclusão da análise, e não uma condição de pesquisa.

## Início rápido (Windows PowerShell)

```powershell
cd "C:\Users\andre\Desktop\radar_longform_v2_codigo_e_testes"
python .\radar_sem_nicho_v3.py --plan-only
python .\radar_sem_nicho_v3.py
```

Requer Python 3.10+ e a chave da YouTube Data API v3. Coloque a sua chave em **`youtube_api_key.txt`**, ao lado do script (uma única linha), sem precisar configurar variáveis do PowerShell. Copie [o arquivo-modelo](./youtube_api_key.example.txt) e renomeie-o para `youtube_api_key.txt`. **Não publique a chave no GitHub**. O modo `--plan-only` não consulta a API.

## Atualização v3.1 — correção de cota diária

A partir da v3.1, respostas HTTP 429 referentes à métrica diária `Search Queries per day` interrompem imediatamente a coleta. O programa escreve `status_coleta.json` e `auditoria_busca_parcial_quota.csv` sem substituir rankings anteriores. Não execute v2 e v3 no mesmo dia sem considerar a cota compartilhada de buscas.

## Versão 3 — principal

- [Código: `radar_sem_nicho_v3.py`](./radar_sem_nicho_v3.py)
- [Documentação detalhada e interpretação das métricas](./README_RADAR_V3.md)
- [Testes automatizados offline](./test_radar_sem_nicho_v3.py)

Pesquisa vídeos sem `q`, `topicId` ou `videoCategoryId`, variando janelas temporais, `regionCode`, duração e ordenação. Por padrão: US, CA, GB, AU e DE; janela de 21 dias; meta de 50 canais com vídeos longos por região. Registra proporções de vídeos, views, médias, medianas, concentração em virais e categorias emergentes **após a descoberta**.

A região da busca não revela a localização dos espectadores. Os resultados são uma **amostra**, não rankings completos do YouTube nem prova de RPM. A API não confirma universalmente Shorts de canais de terceiros: vídeos de até três minutos são classificados como possíveis Shorts até a revisão manual.

## Histórico do projeto

- [Versão 2 — radar long-form com termos de pesquisa](./radar_longform_v2.py)
- [Documentação da v2](./README_LONGFORM_V2.md)
- [Coletor inicial por primeira publicação pública](./coletor_youtube_primeira_publicacao.py)

As versões antigas ficam disponíveis para comparação e reprodutibilidade. Os diretórios locais de resultados são ignorados pelo Git para impedir publicação acidental de dados.
