# AgentCore Runtime / create agent file for runtime
# https://youtu.be/bu2cD1pCFTs?t=2906
import os
import json
import boto3
import logging
from strands import Agent, tool
from typing import Dict, Any , List
from strands.models import BedrockModel
from bedrock_agentcore.runtime import BedrockAgentCoreApp  # for agentcore
from bedrock_agentcore.memory.session import MemorySessionManager
from strands.hooks import AgentInitializedEvent , HookProvider, HookRegistry , MessageAddedEvent
from bedrock_agentcore.memory.constants import StrategyType , ConversationalMessage, MessageRole

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s'    
)

logger = logging.getLogger("event-agent")

app = BedrockAgentCoreApp() # for agentcore

MODEL_ID = os.getenv('MODEL_ID')
MEMORY_ID = os.getenv('MEMORY_ID')
REGION = os.getenv('AWS_REGION')
KB_ID = os.getenv('KB_ID')

agent = None
bedrock_agent_runtime = None

class MemoryHookProvider(HookProvider):
    # https://youtu.be/bu2cD1pCFTs?t=2198
    def __init__(self):
        logger.info("Initializing Memory Hook Provider")
        self.memory_session_manager = MemorySessionManager(MEMORY_ID,REGION)


    def on_agent_initialized(self, event: AgentInitializedEvent):
        logger.info("Agent Initialized")

        actor_id = event.agent.state.get("actor_id")

        if not actor_id:
            logger.warning("Missing actor_id")
            return
        try:
            preferences = self.memory_session_manager.search_long_term_memories(
                namespace_prefix=f"/users/{actor_id}/preferences",
                query="what are the user's preferences",
                top_k=5
            )

            if preferences:
                logger.info(f"User preferences: {preferences}")
                pref_messages = []
                for pref in preferences:
                    pref_text = pref.get('content',{}).get('text','')
                    if pref_text:
                        try:
                            pref_json = json.loads(pref_text)
                            pref_messages.append(f"- {pref_json.get('preferences', pref_text)}")
                        except:
                            pref_messages.append(f"{pref_text}\n")
                if pref_messages:
                    context = "\n".join(pref_messages)
                    event.agent.system_prompt += f"**User Preferences {context}"
                    logger.info("Addeded user preference")
            else:
                logger.info("No user preferences found")
        except Exception as e:
            logger.error(f"Error retrieving user preferences: {e}")

    def on_message_added(self, event: MessageAddedEvent):
        logger.info("Message Added")
        actor_id = event.agent.state.get("actor_id")
        session_id = event.agent.state.get("session_id")

        if not actor_id or not session_id:
            logger.warning("Missing actor_id or session_id")
            return

        try:
            messages = event.agent.messages
            last_message = messages[-1]
            message_content = str(last_message.get("content", ""))
            if last_message["role"] == "user":
                message_role = MessageRole.USER
            elif last_message["role"] == "assistant":
                message_role = MessageRole.ASSISTANT

            self.memory_session_manager.add_turns(
                actor_id=actor_id,
                session_id=session_id,
                messages=[
                    ConversationalMessage(
                      message_content, message_role
                    )
                ]
            )
            logger.info("Added message to memory")
        except Exception as e:
            logger.error(f"Error adding message to memory: {e}")

    def register_hooks(self, registry: HookRegistry):
        logger.info("Registering Memory Hooks")
        registry.add_callback(AgentInitializedEvent, self.on_agent_initialized)
        registry.add_callback(MessageAddedEvent, self.on_message_added)

print("\n Memory Hook Provider Created")

@tool
def search_reinvent_sessions(query: str, max_results: int = 3) -> List[Dict[str, Any]]:
    """Search for employee details from knowledge based using semantic search.
    Use this tool when user ask for employee details.

    Args :
      query: The search query.
      max_results: The maximum number of results to return.

    Returns:
      A list of employee details.

    """

    try:
        logger.info(f"Searching KB with query :{query}")

        response = bedrock_agent_runtime.retrieve(
            knowledgeBaseId=KB_ID,
            retrievalQuery={'text': query},
            retrievalConfiguration={
                'vectorSearchConfiguration': {
                    'numberOfResults': min(max_results,10)
                }
            }
        )

        results = []
        for idx, item in enumerate[Any](response.get('retrievalResults',[]),1):
            result = {
                'rank': idx,
                'content': item.get('content',{}).get('text',''),
                'score': item.get('score',0.0)
            }
            results.append(result)
        logger.info(f"Found {len(results)} RIV sessions")
        return results
    except Exception as e:
        logger.error(f"Error searching KB: {e}")
        return [{"error": f"Failed to search KB : {str(e)}"}]
print("\n KB Search Tool Created")


def initialize_agent(actor_id, session_id):
    """Initialize the agent"""
    global agent

    model = BedrockModel(model_id=MODEL_ID)
    memory_hook = MemoryHookProvider()

    agent = Agent(
        model=model,
        hooks=[memory_hook],
        tools=[search_reinvent_sessions],
        system_prompt="""Your are a intelligent assistant that helps users find information 
        about employee leaves, leave policy, employee information. 
        If you get enough information in the first search don't do additional tool calls. 
        Remember user preferences and provide personalized recommendations""",
        state={
            "actor_id": actor_id,
            "session_id": session_id
        }
    )

@app.entrypoint
def runtime_agent(payload, context):
    """Main entry point for the runtime agent"""
    global agent

    user_input = payload.get("prompt")
    actor_id = payload.get("actor_id")
    session_id = contect.session_id

    if not user_input:
        return "Error: Missiong 'prompt' field"
    
    if agent is None:
        initialize_agent(actor_id, session_id)
    else:
        agent.state["session_id"] = session_id


    response = agent(user_input)
    return response.message['content'][0]['text']

if __name__ == "__main__":
    app.run()



