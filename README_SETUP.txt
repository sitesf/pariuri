INSTRUCTIUNI GITHUB SECRETS

1. Intra in repository-ul tau GitHub.
2. Mergi la Settings.
3. Mergi la Secrets and variables.
4. Apasa Actions.
5. Apasa New repository secret.
6. Adauga aceste secrets:

OPENAI_API_KEY
Cheia ta OpenAI. Necesara daca folosesti LLM_PROVIDER=openai.

GEMINI_API_KEY
Cheia ta Gemini. Necesara daca folosesti LLM_PROVIDER=gemini.

LLM_PROVIDER
Valoare recomandata: openai sau gemini.

OPENAI_MODEL
Valoare recomandata: gpt-4o-mini.

GEMINI_MODEL
Valoare recomandata: gemini-1.5-flash.

API_FOOTBALL_KEY
Cheia ta de la API-Football, API-SPORTS.

API_FOOTBALL_HOST
Valoare recomandata: v3.football.api-sports.io.

ORE CRON
GitHub Actions foloseste UTC.
Romania are ora UTC+2 iarna si UTC+3 vara.
Workflow-ul de stiri ruleaza la 07:00, 10:00, 14:00, 17:00 UTC, adica aproximativ 10:00, 13:00, 17:00, 20:00 in Romania vara.
Workflow-ul de meciuri ruleaza la 05:00 UTC, adica aproximativ 08:00 in Romania vara.
