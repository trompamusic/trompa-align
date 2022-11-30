from flask import Flask, request
from flask_cors import CORS, cross_origin
from pprint import pprint
import json
app = Flask(__name__)
cors = CORS(app)
app.config["DEBUG"] = True
app.config["CORS_HEADERS"] = 'Content-Type'


@app.route("/midiBatch", methods=['POST'])
@cross_origin()
def receiveMidiBatch():
    print("hmm.")
    midi = json.loads('[' + request.get_data().decode('UTF-8') + ']')
    print("Received: ")
    pprint(midi)
    return json.dumps({'success':True}), 200, {'ContentType': 'application/json'}
    
