# pylint:disable=all
from agents import Agent, Runner
import asyncio


class OpenAiApi:
    def __init__(self):
        pass

    def triage_agent(self):
        comment_agent = Agent(
            name="Social media comment specialist",
            instructions="You are realestate agen who handles a comment on instagram posts about a property listing.",
        )

        dm_agent = Agent(
            name="Social media DM specialist",
            instructions="You are realestate agen who handles a DM on instagram of your company profile.",
        )

        return Agent(
            name="Realestate - Triage agent",
            instructions="Handoff to the appropriate agent based on the type of webhook event, if comment handoff to Social media comment specialist if DM handoff to Social media DM specialist.",
            handoffs=[comment_agent, dm_agent],
        )

    
    async def main(self, input_message):
        result = await Runner.run(self.triage_agent(), input=input_message)
        print(result.final_output)