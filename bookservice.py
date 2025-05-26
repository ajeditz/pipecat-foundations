from flask import Flask, request, jsonify, Response
import os
import uuid
import json
import logging
from datetime import datetime
import time
import threading
import queue
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Message queue for SSE (Server-Sent Events)
message_queue = queue.Queue()

@app.route('/trigger-prompt', methods=['POST'])
def trigger_prompt():
    """Endpoint to receive booking requests from voice bot and forward to frontend"""
    try:
        # Get the data from request
        data = request.json or {}
        
        # Extract basic information
        # service_type = data.get('service_type', 'general')
        user_message = data.get('user_message', '')
        source = data.get('source', 'voice_bot')
        
        # Create a simple, clean prompt for the chatbot
        # prompt = create_booking_prompt(user_message)
        
        # Create message for frontend
        message = {
            "event_type": "new_prompt",
            "timestamp": datetime.now().isoformat(),
            "session_id": str(uuid.uuid4()),
            # "prompt": prompt,
            # "service_type": service_type,
            "source": source,
            "user_message": user_message
        }
        
        # Add to message queue for SSE clients
        message_queue.put(message)
        
        logger.info(f"Booking request received; Message: {user_message[:100]}...")
        
        return jsonify({
            "status": "success",
            "message": "Booking request has been processed and sent to chatbot",
            "data": {
                # "service_type": service_type,
                "session_id": message["session_id"]
            }
        })
        
    except Exception as e:
        logger.error(f"Error processing booking request: {str(e)}")
        return jsonify({
            "status": "error",
            "message": f"Error: {str(e)}"
        }), 500

# def create_booking_prompt(service_type: str, user_message: str) -> str:
#     """Create an appropriate initial prompt for the chatbot based on service type"""
    
#     # Clean and prepare the user message
#     user_context = user_message.strip()
    
#     # Service-specific prompts
#     prompts = {
#         "hotel": f"Hello! I understand you're looking to book a hotel. Based on your request: '{user_context}', I'm here to help you find and book the perfect accommodation. Let me gather some details to show you the best available options.",
        
#         "flight": f"Hi there! I see you want to book a flight. From your message: '{user_context}', I'll help you find the best flight options. Let me ask a few questions to get you the most suitable flights.",
        
#         "restaurant": f"Welcome! I understand you'd like to make a restaurant reservation. Based on what you mentioned: '{user_context}', I'm here to help you book a table. Let me gather some information to find the perfect spot for you.",
        
#         "travel": f"Hello! I see you're interested in travel booking. From your request: '{user_context}', I'm here to help you plan and book your trip. Let's start by getting some details about your travel preferences.",
        
#         "general": f"Hi! I understand you'd like to make a booking. Based on your request: '{user_context}', I'm here to help you with your reservation. Let me ask a few questions to assist you better."
#     }
    
#     return prompts.get(service_type, prompts["general"])

@app.route('/listen', methods=['GET'])
def listen():
    """SSE endpoint for frontend to listen for new booking requests"""
    def event_stream():
        while True:
            try:
                # Get message from queue (blocking with timeout)
                message = message_queue.get(timeout=30)
                
                # Format as SSE event
                data = f"data: {json.dumps(message)}\n\n"
                yield data
                message_queue.task_done()
                
            except queue.Empty:
                # Send keepalive comment to prevent connection timeout
                yield ": keepalive\n\n"
            except Exception as e:
                logger.error(f"Error in event stream: {e}")
                break
                
    return Response(event_stream(), mimetype="text/event-stream")

@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    return jsonify({
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "service": "booking-service"
    })

@app.route('/status', methods=['GET'])
def get_status():
    """Get service status and queue information"""
    return jsonify({
        "status": "running",
        "queue_size": message_queue.qsize(),
        "timestamp": datetime.now().isoformat()
    })

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    logger.info(f"Starting booking service on port {port}")
    app.run(host='0.0.0.0', port=port, debug=True, threaded=True)