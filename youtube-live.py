import subprocess
import json
import logging
from flask import Flask, request, Response, jsonify

app = Flask(__name__)

# Set up logging to only show warnings and errors
logging.basicConfig(level=logging.WARNING)

@app.route('/stream', methods=['GET'])
def stream():
    url = request.args.get('url')
    if not url:
        return jsonify({'error': 'URL parameter is required'}), 400

    # First, get stream info to detect stream type
    try:
        info_command = ['streamlink', '--json', url]
        info_process = subprocess.Popen(info_command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        info_output, info_error = info_process.communicate()

        if info_process.returncode != 0:
            logging.error(f'Streamlink error: {info_error.decode()}')
            return jsonify({'error': 'Failed to retrieve stream info'}), 500

        # Parse the JSON output
        stream_info = json.loads(info_output)

        # Determine the best quality available
        best_quality = stream_info['streams'].get('best')
        if not best_quality:
            return jsonify({'error': 'No valid streams found'}), 404

        # Command to run Streamlink for the detected stream type
        command = [
            'streamlink',
            url,
            'best',
            '--hls-live-restart',
            '--stdout'
        ]

        # Create a subprocess to run Streamlink and stream output
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

        def generate():
            while True:
                data = process.stdout.read(4096)
                if not data:
                    break
                yield data

            process.stdout.close()
            process.stderr.close()
            process.wait()

        return Response(generate(), content_type='video/mp2t')

    except Exception as e:
        logging.error(f'Error occurred: {str(e)}')
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=6095)
