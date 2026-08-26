import json
import logging
from typing import Generator
import ollama
from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse, StreamingHttpResponse
from django.views.decorators.csrf import csrf_exempt
from .models import Conversation, ChatMessage

logger = logging.getLogger(__name__)

# Default preferred model fallback order
DEFAULT_MODELS = ['jarvis-ft:latest', 'qwen3:1.7b', 'llama3.2:3b']
_CACHED_MODEL = None
MAX_HISTORY_TURNS = 12  # Bound context history to speed up Ollama generation

def get_ollama_model() -> str:
    """Retrieve and cache the available Ollama model to avoid listing models on every request."""
    global _CACHED_MODEL
    if _CACHED_MODEL:
        return _CACHED_MODEL

    try:
        models_response = ollama.list()
        available = []
        if hasattr(models_response, 'models') and models_response.models:
            available = [getattr(m, 'model', getattr(m, 'name', '')) for m in models_response.models]
        elif isinstance(models_response, dict) and models_response.get('models'):
            available = [m.get('name', '') for m in models_response['models']]

        for pref in DEFAULT_MODELS:
            if pref in available or any(pref in name for name in available):
                _CACHED_MODEL = pref
                return _CACHED_MODEL

        if available:
            _CACHED_MODEL = available[0]
            return _CACHED_MODEL
    except Exception as e:
        logger.warning(f"Could not query Ollama models: {e}")

    _CACHED_MODEL = "jarvis-ft:latest"
    return _CACHED_MODEL

def build_messages_payload(history_messages) -> list:
    """Construct formatted message history for Ollama with bounded recent turns for optimal speed."""
    messages = [{
        'role': 'system',
        'content': (
            'You are Jarvis AI, a highly intelligent, fast, and helpful AI assistant. '
            'Answer clearly and accurately. Use Markdown for formatting and code blocks.'
        )
    }]
    # Bound to recent messages to avoid context bloat & slow LLM generation
    bounded_history = history_messages[-MAX_HISTORY_TURNS:] if len(history_messages) > MAX_HISTORY_TURNS else history_messages
    for msg in bounded_history:
        role = 'user' if msg.sender == 'user' else 'assistant'
        messages.append({'role': role, 'content': msg.content})
    return messages

def index(request, conversation_id=None):
    conversations = Conversation.objects.all()
    active_conversation = None
    chat_messages = []

    if conversation_id:
        active_conversation = get_object_or_404(Conversation, id=conversation_id)
        chat_messages = active_conversation.messages.all()

    return render(request, 'todo/index.html', {
        'conversations': conversations,
        'active_conversation': active_conversation,
        'chat_messages': chat_messages,
        'model_name': get_ollama_model(),
    })

def new_chat(request):
    return redirect('index')

def delete_chat(request, conversation_id):
    conversation = get_object_or_404(Conversation, id=conversation_id)
    conversation.delete()
    return redirect('index')

@csrf_exempt
def chat_api(request):
    """High-performance streaming and standard chat endpoint."""
    if request.method != "POST":
        return JsonResponse({"error": "Only POST allowed"}, status=405)

    try:
        data = json.loads(request.body) if request.body else request.POST
        prompt = data.get("message", "").strip()
        conversation_id = data.get("conversation_id")
        stream_requested = data.get("stream", True)

        if not prompt:
            return JsonResponse({"error": "Message content is required"}, status=400)

        # Get or create conversation
        if conversation_id:
            conversation = get_object_or_404(Conversation, id=conversation_id)
        else:
            title = prompt[:35] + ("..." if len(prompt) > 35 else "")
            conversation = Conversation.objects.create(title=title)

        # Save user message
        user_msg = ChatMessage.objects.create(
            conversation=conversation,
            sender='user',
            content=prompt
        )

        # Retrieve recent history efficiently
        history = list(conversation.messages.order_by('created_at'))
        messages_payload = build_messages_payload(history)
        model_name = get_ollama_model()

        if stream_requested:
            def stream_generator() -> Generator[str, None, None]:
                full_reply = []
                # First event sends metadata
                yield f"data: {json.dumps({'type': 'init', 'conversation_id': str(conversation.id), 'conversation_title': conversation.title, 'user_time': user_msg.created_at.strftime('%H:%M')})}\n\n"
                
                try:
                    stream = ollama.chat(model=model_name, messages=messages_payload, stream=True)
                    for chunk in stream:
                        delta = chunk.get('message', {}).get('content', '') if isinstance(chunk, dict) else getattr(chunk.message, 'content', '')
                        if delta:
                            full_reply.append(delta)
                            yield f"data: {json.dumps({'type': 'chunk', 'delta': delta})}\n\n"
                    
                    complete_text = "".join(full_reply)
                    ai_msg = ChatMessage.objects.create(
                        conversation=conversation,
                        sender='ai',
                        content=complete_text
                    )

                    yield f"data: {json.dumps({'type': 'done', 'ai_time': ai_msg.created_at.strftime('%H:%M')})}\n\n"
                except Exception as stream_err:
                    logger.error(f"Streaming error: {stream_err}")
                    yield f"data: {json.dumps({'type': 'error', 'error': str(stream_err)})}\n\n"

            response = StreamingHttpResponse(stream_generator(), content_type='text/event-stream')
            response['Cache-Control'] = 'no-cache, no-transform'
            response['X-Accel-Buffering'] = 'no'
            return response

        # Non-streaming fallback
        res = ollama.chat(model=model_name, messages=messages_payload, stream=False)
        content = res.get('message', {}).get('content', '') if isinstance(res, dict) else res.message.content
        
        ai_msg = ChatMessage.objects.create(
            conversation=conversation,
            sender='ai',
            content=content
        )

        return JsonResponse({
            "status": "success",
            "conversation_id": str(conversation.id),
            "conversation_title": conversation.title,
            "user_message": {
                "id": str(user_msg.id),
                "content": user_msg.content,
                "created_at": user_msg.created_at.strftime("%H:%M")
            },
            "ai_message": {
                "id": str(ai_msg.id),
                "content": ai_msg.content,
                "created_at": ai_msg.created_at.strftime("%H:%M")
            }
        })
    except Exception as e:
        logger.error(f"Error in chat_api: {e}")
        return JsonResponse({"error": str(e)}, status=500)
