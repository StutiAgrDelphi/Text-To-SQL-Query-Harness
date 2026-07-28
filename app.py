from agent import build_agent
from agent_framework.devui import serve

agent = build_agent()

serve(entities=[agent], auto_open=True, auth_enabled=False)
# Opens browser to http://localhost:8080