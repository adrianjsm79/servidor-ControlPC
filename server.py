from flask import Flask, request, jsonify, render_template_string, redirect, url_for, send_from_directory
import psycopg2
import os
import socket
import time
from datetime import datetime, timedelta

app = Flask(__name__)

UPLOAD_FOLDER = os.path.join(os.getcwd(), 'archivos_subidos')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# === Conexión a la base de datos ===
DATABASE_URL = os.getenv("DATABASE_URL")
conn = psycopg2.connect(DATABASE_URL, sslmode='require')
cursor = conn.cursor()

# === Intentar agregar columna si no existe ===
try:
    cursor.execute("ALTER TABLE pcs ADD COLUMN ultima_actividad TIMESTAMP DEFAULT NOW();")
    conn.commit()
except psycopg2.errors.DuplicateColumn:
    conn.rollback()

# === Crear tablas si no existen ===
cursor.execute("""
CREATE TABLE IF NOT EXISTS pcs (
    nombre TEXT PRIMARY KEY,
    ip TEXT,
    ultima_actividad TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS comandos (
    nombre TEXT PRIMARY KEY,
    accion TEXT
);
""")
conn.commit()

HTML_TEMPLATE = """<html>... (recortado por brevedad, sin cambios) ...</html>"""

@app.route('/')
def inicio():
    try:
        cursor.execute("SELECT nombre, ip, ultima_actividad FROM pcs;")
        pcs = cursor.fetchall()
        ahora = datetime.utcnow()
        estados = {}
        resultado = [(nombre, ip) for nombre, ip, _ in pcs]

        for nombre, ip, ultima in pcs:
            if ultima and ahora - ultima < timedelta(seconds=15):
                estados[nombre] = "conectado"
            else:
                estados[nombre] = "desconectado"

        conn.commit()
        return render_template_string(HTML_TEMPLATE, pcs=resultado, estados=estados)
    except Exception as e:
        conn.rollback()
        return f"<h1>Error en el servidor</h1><p>{e}</p>", 500

@app.route('/actualizar_actividad/<nombre>', methods=['POST'])
def actualizar_actividad(nombre):
    try:
        cursor.execute("""
            UPDATE pcs SET ultima_actividad = NOW() WHERE nombre = %s;
        """, (nombre,))
        conn.commit()
        return jsonify({"estado": "actualizado"}), 200
    except Exception as e:
        conn.rollback()
        return jsonify({"error": str(e)}), 500

@app.route('/eliminar/<nombre>', methods=['POST'])
def eliminar_pc(nombre):
    clave = request.form.get("clave")
    if clave == "admin123":
        try:
            cursor.execute("SELECT ultima_actividad FROM pcs WHERE nombre = %s;", (nombre,))
            resultado = cursor.fetchone()
            if resultado:
                ultima = resultado[0]
                if ultima and datetime.utcnow() - ultima < timedelta(seconds=15):
                    return "No se puede eliminar una PC activa."
            cursor.execute("DELETE FROM pcs WHERE nombre = %s;", (nombre,))
            cursor.execute("DELETE FROM comandos WHERE nombre = %s;", (nombre,))
            conn.commit()
            return "PC eliminada correctamente."
        except Exception as e:
            conn.rollback()
            return f"Error al eliminar: {e}", 500
    else:
        return "Contraseña incorrecta."

@app.route('/registrar', methods=['POST'])
def registrar_pc():
    try:
        data = request.json
        nombre = data.get("nombre")
        ip = request.remote_addr
        if nombre:
            cursor.execute("""
            INSERT INTO pcs (nombre, ip, ultima_actividad) VALUES (%s, %s, NOW())
            ON CONFLICT (nombre) DO UPDATE SET ip = EXCLUDED.ip, ultima_actividad = NOW();
            """, (nombre, ip))
            conn.commit()
            return jsonify({"estado": "registrado", "ip": ip}), 200
        return jsonify({"error": "Nombre requerido"}), 400
    except Exception as e:
        conn.rollback()
        return jsonify({"error": str(e)}), 500

@app.route('/pcs', methods=['GET'])
def obtener_pcs():
    ahora = datetime.utcnow()
    cursor.execute("SELECT nombre, ip, ultima_actividad FROM pcs;")
    pcs = cursor.fetchall()

    resultado = []
    for nombre, ip, ultima in pcs:
        estado = "conectado" if ultima and ahora - ultima < timedelta(seconds=15) else "desconectado"
        resultado.append({
            "nombre": nombre,
            "ip": ip,
            "estado": estado
        })

    return jsonify(resultado)

@app.route('/comando/<nombre>/<accion>', methods=['GET'])
def enviar_comando(nombre, accion):
    try:
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
    except Exception as e:
        conn.rollback()
        return jsonify({"error": str(e)}), 500

@app.route('/comando/<nombre>/pendiente', methods=['GET'])
def obtener_comando_pendiente(nombre):
    try:
        cursor.execute("SELECT accion FROM comandos WHERE nombre = %s;", (nombre,))
        resultado = cursor.fetchone()
        if resultado:
            accion = resultado[0]
            cursor.execute("DELETE FROM comandos WHERE nombre = %s;", (nombre,))
            conn.commit()
            return jsonify({"accion": accion})
        conn.commit()
        return jsonify({"accion": None})
    except Exception as e:
        conn.rollback()
        return jsonify({"error": str(e)}), 500

@app.route('/archivo/<nombre>', methods=['POST'])
def recibir_archivo(nombre):
    archivo = request.files.get('archivo')
    if not archivo:
        return jsonify({"error": "No se envió ningún archivo"}), 400

    carpeta_destino = os.path.join(UPLOAD_FOLDER, nombre)
    os.makedirs(carpeta_destino, exist_ok=True)
    ruta = os.path.join(carpeta_destino, archivo.filename)
    archivo.save(ruta)

    return jsonify({"estado": "archivo recibido", "ruta": ruta}), 200

if __name__ == '__main__':
    app.run(debug=True)
