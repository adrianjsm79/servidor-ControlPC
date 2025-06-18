from flask import Flask, request, jsonify
import psycopg2
import os

app = Flask(__name__)

# === Conexión a la base de datos ===
DATABASE_URL = os.getenv("DATABASE_URL")
conn = psycopg2.connect(DATABASE_URL, sslmode='require')
cursor = conn.cursor()

# === Crear tablas si no existen ===
cursor.execute("""
CREATE TABLE IF NOT EXISTS pcs (
    nombre TEXT PRIMARY KEY,
    ip TEXT
);

CREATE TABLE IF NOT EXISTS comandos (
    nombre TEXT PRIMARY KEY,
    accion TEXT
);
""")
conn.commit()

@app.route('/registrar', methods=['POST'])
def registrar_pc():
    data = request.json
    nombre = data.get("nombre")
    ip = request.remote_addr
    if nombre:
        cursor.execute("""
        INSERT INTO pcs (nombre, ip) VALUES (%s, %s)
        ON CONFLICT (nombre) DO UPDATE SET ip = EXCLUDED.ip;
        """, (nombre, ip))
        conn.commit()
        return jsonify({"estado": "registrado", "ip": ip}), 200
    return jsonify({"error": "Nombre requerido"}), 400

@app.route('/pcs', methods=['GET'])
def obtener_pcs():
    cursor.execute("SELECT nombre, ip FROM pcs;")
    pcs = cursor.fetchall()
    return jsonify([{ "nombre": nombre, "ip": ip } for nombre, ip in pcs])

@app.route('/comando/<nombre>/<accion>', methods=['GET'])
def enviar_comando(nombre, accion):
    cursor.execute("SELECT ip FROM pcs WHERE nombre = %s;", (nombre,))
    resultado = cursor.fetchone()
    if not resultado:
        return jsonify({"error": "PC no registrada"}), 404

    ip = resultado[0]
    cursor.execute("""
    INSERT INTO comandos (nombre, accion) VALUES (%s, %s)
    ON CONFLICT (nombre) DO UPDATE SET accion = EXCLUDED.accion;
    """, (nombre, accion))
    conn.commit()

    return jsonify({
        "ip_destino": ip,
        "accion": accion,
        "estado": "pendiente"
    })

@app.route('/comando/<nombre>/pendiente', methods=['GET'])
def obtener_comando_pendiente(nombre):
    cursor.execute("SELECT accion FROM comandos WHERE nombre = %s;", (nombre,))
    resultado = cursor.fetchone()
    if resultado:
        accion = resultado[0]
        cursor.execute("DELETE FROM comandos WHERE nombre = %s;", (nombre,))
        conn.commit()
        return jsonify({"accion": accion})
    return jsonify({"accion": None})

@app.route('/')
def inicio():
    return "Servidor de ControlPC activo", 200

if __name__ == '__main__':
    app.run(debug=True)
