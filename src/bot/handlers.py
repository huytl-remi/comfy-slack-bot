import uuid
from src.utils.config import load_config
from src.utils.logging_config import logger
from src.utils.exceptions import SlackAPIError, SDSlackBotError
from src.queue.request_queue import request_queue
from .views import open_image_gen_modal, open_remix_modal

config = load_config()

def register_handlers(app):
    @app.command("/generate_image")
    async def start_image_generation(ack, body, client):
        await ack()
        try:
            await open_image_gen_modal(client, body["trigger_id"], body["channel_id"])
        except Exception as e:
            logger.error(f"Error opening modal: {str(e)}")
            raise SlackAPIError(f"Failed to open image generation modal: {str(e)}")

    @app.action("regenerate_image")
    async def handle_regenerate(ack, body, client):
        await ack()
        user_id = body["user"]["id"]
        request_id = body["actions"][0]["value"].split("_")[1]

        try:
            # Fetch original request details
            original_request = await request_queue.get_request_by_id(request_id)
            if not original_request:
                raise SDSlackBotError("Original request not found")

            # Create a new request with the same parameters
            new_request_id = str(uuid.uuid4())
            new_request = {
                'id': new_request_id,
                'user_id': user_id,
                'channel': original_request['channel'],
                'params': original_request['params']
            }

            # Add new request to queue
            queue_position = await request_queue.add_request(new_request)

            # Send message about queued regeneration
            await client.chat_postMessage(
                channel=user_id,
                text=f"Your image regeneration request has been queued. You are number {queue_position} in line. "
                     f"Estimated wait time: {request_queue.estimate_wait_time(queue_position)} seconds."
            )

        except Exception as e:
            logger.error(f"Error handling regenerate action: {str(e)}")
            await client.chat_postMessage(
                channel=user_id,
                text=f"An error occurred while processing your regeneration request: {str(e)}"
            )

    @app.action("remix_image")
    async def handle_remix(ack, body, client):
        await ack()
        user_id = body["user"]["id"]
        request_id = body["actions"][0]["value"].split("_")[1]

        try:
            # Fetch original request details
            original_request = await request_queue.get_request_by_id(request_id)
            if not original_request:
                raise SDSlackBotError("Original request not found")

            # Open remix modal
            await open_remix_modal(client, body["trigger_id"], original_request['params'])

        except Exception as e:
            logger.error(f"Error handling remix action: {str(e)}")
            await client.chat_postMessage(
                channel=user_id,
                text=f"An error occurred while processing your remix request: {str(e)}"
            )
