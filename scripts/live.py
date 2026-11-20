"""Live desk: one capybara reads Stripe through Airbyte's agent connector and reconciles it with SingleStore.
usage: python scripts/live.py ["question"]"""
import asyncio, json, logging, sys, uuid
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from capyteam import sandbox
from capyteam.agent import open_session
from capyteam.analytics import analytics
from capyteam.practice import ensure_yard

Q = ("Morning money check, please: through Airbyte, look at Stripe for the last 30 days. How much came in, which refunds were made, "
     "and is there any dispute I need to answer? Then compare Stripe's refunds with what CapyTeam itself did, and tell me which refunds "
     "were made outside CapyTeam so I can book them.")

async def main():
    ensure_yard()
    world = "live"
    sandbox.reset_world(world, "live")
    sid = f"live-{uuid.uuid4().hex[:8]}"
    s = await open_session(sid, mode="live", source="airbyte", world_id=world, invoke_urls={}, scenario="morning-money-check", capy="Hazel")
    reply = await s.respond(sys.argv[1] if len(sys.argv) > 1 else Q)
    print(f"[{s.capy} {s.version} via Airbyte ({s.airbyte_mode})]\n{reply}\n\ncredits={s.usage.credits} tools={s.tool_count}")
    await s.end("done")
    analytics.flush()
    Path(".runtime/live.json").write_text(json.dumps({"session": sid, "reply": reply, "mode": s.airbyte_mode}, indent=1))

logging.basicConfig(level=logging.WARNING)
asyncio.run(main())
