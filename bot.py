import asyncio
import os
import sys
import argparse
import json
import  base64
import requests
from pipecat.adapters.schemas.function_schema import FunctionSchema
from pipecat.services.azure import AzureLLMService, AzureSTTService, AzureTTSService, Language
from pipecat.adapters.schemas.tools_schema import ToolsSchema
from pipecat.frames.frames import TTSSpeakFrame, EndFrame, EndTaskFrame
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineParams, PipelineTask
from pipecat.frames.frames import LLMMessagesFrame, EndFrame
from pipecat.processors.aggregators.openai_llm_context import OpenAILLMContext
from pipecat.services.openai import OpenAILLMService
from pipecat.services.llm_service import FunctionCallParams
from pipecat.services.elevenlabs import ElevenLabsTTSService
from pipecat.services.cartesia import CartesiaTTSService
from pipecat.transports.services.daily import DailyParams, DailyTransport
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from pipecat.frames.frames import (
    OutputImageRawFrame,
    SpriteFrame,
    Frame,
    LLMMessagesFrame,
    TTSAudioRawFrame,
    TTSStoppedFrame,
)

from PIL import Image

from prompt import prompt

from loguru import logger

from dotenv import load_dotenv

load_dotenv(override=True)

logger.remove(0)
logger.add(sys.stderr, level="DEBUG")

daily_api_key = os.getenv("DAILY_API_KEY", "")
daily_api_url = os.getenv("DAILY_API_URL", "https://api.daily.co/v1")
BOOKING_SERVICE_URL = os.getenv("BOOKING_SERVICE_URL", "http://localhost:5000/trigger-prompt")

# async def fetch_weather_from_api(params: FunctionCallParams):
#     await params.llm.push_frame(TTSSpeakFrame("Let me check on that."))
#     await params.result_callback({"conditions": "nice", "temperature": "75"})

async def booking_service(params: FunctionCallParams):
    """Handle booking requests by sending to the booking service"""
    await params.llm.push_frame(TTSSpeakFrame("Let me help you with that booking by transferring your request to our booking service."))
    try:
        logger.info(f"Received booking request: {params.arguments}")
        logger.info(f"The user message received in the booking service function is: {params.arguments['user_message']}")
        payload = {
            "user_message": f"{params.arguments['user_message']}",
            # "service_type": service_type,
            "source": "voice_bot",
            # "user_message": user_message
            "status": True,
        }
        
        response = requests.post(BOOKING_SERVICE_URL, json=payload, timeout=5)
        logger.info(f"Sent booking request to service: {response.status_code}")
        await params.llm.queue_frame(EndTaskFrame(), FrameDirection.UPSTREAM)
        await params.result_callback("Goodbye")
        return response.status_code == 200
        
    except Exception as e:
        logger.error(f"Error sending to booking service: {e}")
        return False




async def main(room_url: str, token: str):
    transport = DailyTransport(
        room_url,
        token,
        "Paddi AI",
        DailyParams(
            api_url=daily_api_url,
            api_key=daily_api_key,
            audio_in_enabled=True,
            audio_out_enabled=True,
            camera_out_enabled=False,
            vad_enabled=True,
            vad_analyzer=SileroVADAnalyzer(),
            transcription_enabled=True,
        ),
    )

    # config_str = base64.b64decode(config_b64).decode()
    # config = json.loads(config_str)

    tts_service = AzureTTSService(
        api_key=os.getenv("AZURE_API_KEY"),
        region=os.getenv("AZURE_REGION"),
        voice=os.getenv("AZURE_VOICE_ID"),

    )

    llm = OpenAILLMService(api_key=os.getenv("OPENAI_API_KEY"), model="gpt-4o")
    llm.register_function("get_current_weather")
    # weather_function = FunctionSchema(
    #     name="get_current_weather",
    #     description="Get the current weather",
    #     properties={
    #         "location": {
    #             "type": "string",
    #             "description": "The city and state, e.g. San Francisco, CA",
    #         },
    #         "format": {
    #             "type": "string",
    #             "enum": ["celsius", "fahrenheit"],
    #             "description": "The temperature unit to use. Infer this from the user's location.",
    #         },
    #     },
    #     required=["location", "format"],
    # )
    # tools = ToolsSchema(standard_tools=[weather_function])

    llm.register_function("booking_service", booking_service)
    booking_function = FunctionSchema(
        name="booking_service",
        description="Handle booking requests by sending to the booking service",
        properties={
            "user_message": {
                "type": "string",
                "description": "The user's message or request for booking assistance, for example, 'I have a meeting in Delhi on 21st may, can you book me a one way flight from mumbai.'",
            }            
        },
        required=["user_message"],
    )
    tools = ToolsSchema(standard_tools=[ booking_function])
    messages = [
        {
            "role": "system",
            "content":prompt,
        },
    ]

    context = OpenAILLMContext(messages, tools)
    context_aggregator = llm.create_context_aggregator(context)
    # ts=TalkingAnimation()

    pipeline = Pipeline(
        [
            transport.input(),
            context_aggregator.user(),
            llm,
            tts_service,
            transport.output(),
            context_aggregator.assistant(),
        ]
    )

    task = PipelineTask(
        pipeline, 
        params=PipelineParams(
            allow_interruptions=True,
            enable_metric=True,
            enable_usage_metrics=True,
            report_only_initial_ttfb=True
            ),
    )

    @transport.event_handler("on_participant_joined")
    async def on_participant_joined(transport, participant):
        await transport.capture_participant_transcription(participant["id"])
        await task.queue_frames([LLMMessagesFrame(messages)])

    @transport.event_handler("on_participant_left")
    async def on_participant_left(transport, participant, reason):
        await task.queue_frame(EndFrame())

    @transport.event_handler("on_call_state_updated")
    async def on_call_state_updated(transport, state):
        if state == "left":
            await task.queue_frame(EndFrame())

    runner = PipelineRunner()

    await runner.run(task)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Pipecat Bot")
    parser.add_argument("-u", required=True,type=str, help="Room URL")
    parser.add_argument("-t",  required=True,type=str, help="Token")
    # parser.add_argument("--config", required=True, help="Base64 encoded configuration")
    args = parser.parse_args()

    asyncio.run(main(args.u, args.t ))