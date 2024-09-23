import subprocess
from flask import Flask, request, Response, jsonify

app = Flask(__name__)

@app.route('/stream', methods=['GET'])
def stream():
    url = request.args.get('url')
    if not url:
        return jsonify({'error': 'URL parameter is required'}), 400

    # Command to run Streamlink
    command = [
        'streamlink',  # Ensure 'streamlink' is in your PATH
        url,
        'best',  # Adjust this if you want a specific quality
        '--hls-live-restart',
        '--stdout'  # Stream to stdout instead of player
    ]

    try:
        # Create a subprocess to run Streamlink and stream output
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

        # Stream the output directly to the client
        def generate():
            while True:
                data = process.stdout.read(1024)
                if not data:
                    break
                yield data

        return Response(generate(), content_type='application/x-mpegURL')

    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=6095)
