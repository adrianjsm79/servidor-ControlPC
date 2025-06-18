from flask import Flask, request, jsonify

app = Flask(__name__)

# Diccionario para registrar PCs conectadas
pcs_registradas = {}

@app.route('/registrar', methods=['POST'])
def registrar_pc():
    data = request.json
    nombre = data.get("nombre")
    ip = request.remote_addr
    if nombre:
        pcs_registradas[nombre] = ip
        return jsonify({"estado": "registrado", "ip": ip}), 200
    return jsonify({"error": "Nombre requerido"}), 400

@app.route('/pcs', methods=['GET'])
def obtener_pcs():
    return jsonify(pcs_registradas)

@app.route('/comando/<nombre>/<accion>', methods=['GET'])
def enviar_comando(nombre, accion):
    ip = pcs_registradas.get(nombre)
    if not ip:
        return jsonify({"error": "PC no registrada"}), 404
    return jsonify({
        "ip_destino": ip,
        "accion": accion
    })

@app.route('/')
def inicio():
    return "Servidor de ControlPC activo", 200

if __name__ == '__main__':
    app.run(debug=True)
