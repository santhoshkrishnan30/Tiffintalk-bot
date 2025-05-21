from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
import db_helper
import generic_helper
import logging
import os

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()

# Mount the frontend directory for static files
app.mount("/static", StaticFiles(directory="E:/Tiffintalk-Bot-FastAPI-main/frontend"), name="static")

inprogress_orders = {}

# Serve index.html for GET requests
@app.get("/", response_class=HTMLResponse)
async def serve_index():
    try:
        with open("E:/Tiffintalk-Bot-FastAPI-main/frontend/index.html", "r") as f:
            html_content = f.read()
        logger.info("Served index.html")
        return HTMLResponse(content=html_content)
    except FileNotFoundError:
        logger.error("index.html not found")
        return HTMLResponse(content="<h1>Error: index.html not found</h1>", status_code=404)

# Handle Dialogflow POST requests
@app.post("/")
async def handle_request(request: Request):
    try:
        payload = await request.json()
        logger.info(f"Received POST payload: {payload}")
        intent = payload['queryResult']['intent']['displayName']
        parameters = payload['queryResult']['parameters']
        output_contexts = payload['queryResult']['outputContexts']
        if not output_contexts:
            logger.error("No output contexts provided")
            return JSONResponse(content={"fulfillmentText": "Error: No output contexts provided"}, status_code=400)
        session_id = generic_helper.extract_session_id(output_contexts[0]["name"])
        logger.info(f"Session ID: {session_id}, Intent: {intent}")
        intent_handler_dict = {
            'order.add - context: ongoing-order': add_to_order,
            'order.remove - context: ongoing-order': remove_from_order,
            'order.complete - context: ongoing-order': complete_order,
            'track.order - context: ongoing-tracking': track_order
        }
        if intent not in intent_handler_dict:
            logger.error(f"Unknown intent: {intent}")
            return JSONResponse(content={"fulfillmentText": f"Error: Unknown intent {intent}"}, status_code=400)
        return intent_handler_dict[intent](parameters, session_id)
    except Exception as e:
        logger.error(f"Error processing request: {str(e)}")
        return JSONResponse(content={"fulfillmentText": f"Error: {str(e)}"}, status_code=400)

def save_to_db(order: dict):
    try:
        next_order_id = db_helper.get_next_order_id()
        for food_item, quantity in order.items():
            rcode = db_helper.insert_order_item(food_item, quantity, next_order_id)
            if rcode == -1:
                return -1
        db_helper.insert_order_tracking(next_order_id, "in progress")
        return next_order_id
    except Exception as e:
        logger.error(f"Error saving to DB: {str(e)}")
        return -1

def complete_order(parameters: dict, session_id: str):
    if session_id not in inprogress_orders:
        fulfillment_text = "I'm having a trouble finding your order. Sorry! Can you place a new order please?"
    else:
        order = inprogress_orders[session_id]
        order_id = save_to_db(order)
        if order_id == -1:
            fulfillment_text = "Sorry, I couldn't process your order due to a backend error. Please place a new order again"
        else:
            order_total = db_helper.get_total_order_price(order_id)
            fulfillment_text = f"Awesome. We have placed your order. Here is your order id # {order_id}. Your order total is {order_total} which you can pay at the time of delivery!"
        del inprogress_orders[session_id]
    return JSONResponse(content={"fulfillmentText": fulfillment_text})

def add_to_order(parameters: dict, session_id: str):
    food_items = parameters["food-item"]
    quantities = parameters["number"]
    if len(food_items) != len(quantities):
        fulfillment_text = "Sorry I didn't understand. Can you please specify food items and quantities clearly?"
    else:
        new_food_dict = dict(zip(food_items, quantities))
        if session_id in inprogress_orders:
            current_food_dict = inprogress_orders[session_id]
            current_food_dict.update(new_food_dict)
            inprogress_orders[session_id] = current_food_dict
        else:
            inprogress_orders[session_id] = new_food_dict
        order_str = generic_helper.get_str_from_food_dict(inprogress_orders[session_id])
        fulfillment_text = f"So far you have: {order_str}. Do you need anything else?"
    return JSONResponse(content={"fulfillmentText": fulfillment_text})

def remove_from_order(parameters: dict, session_id: str):
    if session_id not in inprogress_orders:
        return JSONResponse(content={"fulfillmentText": "I'm having a trouble finding your order. Sorry! Can you place a new order please?"})
    food_items = parameters["food-item"]
    current_order = inprogress_orders[session_id]
    removed_items = []
    no_such_items = []
    for item in food_items:
        if item not in current_order:
            no_such_items.append(item)
        else:
            removed_items.append(item)
            del current_order[item]
    fulfillment_text = ""
    if len(removed_items) > 0:
        fulfillment_text += f'Removed {",".join(removed_items)} from your order! '
    if len(no_such_items) > 0:
        fulfillment_text += f'Your current order does not have {",".join(no_such_items)}. '
    if len(current_order.keys()) == 0:
        fulfillment_text += "Your order is empty!"
    else:
        order_str = generic_helper.get_str_from_food_dict(current_order)
        fulfillment_text += f"Here is what is left in your order: {order_str}"
    return JSONResponse(content={"fulfillmentText": fulfillment_text})

def track_order(parameters: dict, session_id: str):
    order_id = int(parameters['number'])
    order_status = db_helper.get_order_status(order_id)
    if order_status:
        fulfillment_text = f"The order status for order id: {order_id} is: {order_status}"
    else:
        fulfillment_text = f"No order found with order id: {order_id}"
    return JSONResponse(content={"fulfillmentText": fulfillment_text})