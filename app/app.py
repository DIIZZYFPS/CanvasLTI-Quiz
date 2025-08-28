from flask import *

app = Flask(__name__)

@app.route("/api/", methods=['GET'])
def hello_world():
    return {"message": "Hello from Flask!"}

if __name__ == '__main__':
    app.run(debug=True)