from flask import Flask, send_from_directory

from status_api import bp as status_bp


app = Flask(__name__, static_folder=".", static_url_path="")
app.register_blueprint(status_bp)


@app.get("/")
def index():
    return send_from_directory(".", "index.html")


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5050, debug=False)
