from flask import Flask, request, jsonify, render_template_string, redirect, url_for, send_from_directory
import psycopg2
from werkzeug.utils import secure_filename
import os
import socket
import time
from datetime import datetime, timedelta
import requests
from flask_cors import CORS
from werkzeug.exceptions import RequestEntityTooLarge
from uuid import uuid4

UPLOAD_FOLDER = "archivos_temporales"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 2 * 1024 * 1024 * 1024  # 2 GB
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
CORS(app)

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

# === Crear tabla para archivos pendientes si no existe ===
cursor.execute("""
CREATE TABLE IF NOT EXISTS archivos_pendientes (
    nombre TEXT,
    url TEXT
);
""")
conn.commit()

HTML_TEMPLATE = """
<!doctype html>
<html lang=\"es\">
  <head>
    <meta charset=\"utf-8\">
    <title>ControlPC</title>
    <style>
      body { font-family: Arial, sans-serif; margin: 20px; background-color: #f4f4f4; color: #333; }
      h1, h2 { color: #222; }
      ul { list-style: none; padding: 0; }
      li { background: #fff; margin: 10px 0; padding: 10px; border: 1px solid #ccc; border-radius: 6px; display: flex; justify-content: space-between; align-items: center; }
      .estado { font-size: 0.9em; padding: 2px 6px; border-radius: 4px; background-color: #ccc; color: #fff; margin-right: 10px; }
      .conectado { background-color: #2ecc71; }
      .desconectado { background-color: #e67e22; }
      button { background-color: #e74c3c; color: white; border: none; padding: 5px 10px; border-radius: 4px; cursor: pointer; }
      #modal {
        display: none; position: fixed; top: 0; left: 0; width: 100%; height: 100%; background-color: rgba(0,0,0,0.5);
        justify-content: center; align-items: center;
      }
      #modal-content {
        background: white; padding: 20px; border-radius: 8px; text-align: center; min-width: 300px;
      }
      #modal input[type='password'] {
        padding: 5px; margin-top: 10px; width: 100%;
      }
      #modal button {
        margin-top: 10px;
      }
      .mensaje {
        margin-top: 10px;
        color: red;
      }
    </style>
    <script>
      function solicitarClave(nombre) {
        document.getElementById('nombre_pc').value = nombre;
        document.getElementById('clave').value = '';
        document.getElementById('mensaje').innerText = '';
        document.getElementById('modal').style.display = 'flex';
      }

      function cerrarModal() {
        document.getElementById('modal').style.display = 'none';
      }

      async function enviarClave() {
        const nombre = document.getElementById('nombre_pc').value;
        const clave = document.getElementById('clave').value;

        const formData = new FormData();
        formData.append('clave', clave);

        const respuesta = await fetch(`/eliminar/${nombre}`, {
          method: 'POST',
          body: formData
        });

        const texto = await respuesta.text();
        document.getElementById('mensaje').innerHTML = texto;

        if (respuesta.status === 200) {
          setTimeout(() => location.reload(), 1500);
        }
      }

      setInterval(() => location.reload(), 10000);
    </script>
  </head>
  <body>
    <h1>Servidor de ControlPC activo</h1>
    <h2>Equipos registrados</h2>
    <ul>
      {% for nombre, ip in pcs %}
        <li>
          <span><span class=\"estado {{ estados[nombre] }}\">{{ estados[nombre] }}</span>{{ nombre }} - {{ ip }}</span>
          <button onclick=\"solicitarClave('{{ nombre }}')\">Eliminar</button>
        </li>
      {% endfor %}
    </ul>

    <div id=\"modal\">
      <div id=\"modal-content\">
        <h3>Confirmar eliminación</h3>
        <input type=\"hidden\" id=\"nombre_pc\">
        <input type=\"password\" id=\"clave\" placeholder=\"Contraseña\">
        <div class=\"mensaje\" id=\"mensaje\"></div>
        <button onclick=\"enviarClave()\">Confirmar</button>
        <button onclick=\"cerrarModal()\">Cancelar</button>
      </div>
    </div>
  </body>
</html>
"""

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
        return jsonify({"accion": None})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/archivo/<nombre>', methods=['POST'])
def subir_archivo(nombre):
    archivo = request.files.get('archivo')
    if not archivo:
        return "No se envió ningún archivo", 400

    try:
        filename = secure_filename(archivo.filename)
        unique_id = uuid4().hex[:8]
        filename = f"{unique_id}_{filename}"
        ruta = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        
        # Guardar el archivo en chunks
        with open(ruta, 'wb') as f:
            while True:
                chunk = archivo.stream.read(8192)
                if not chunk:
                    break
                f.write(chunk)

        cursor.execute("""
            INSERT INTO comandos (nombre, accion) VALUES (%s, %s)
            ON CONFLICT (nombre) DO UPDATE SET accion = EXCLUDED.accion;
        """, (nombre, f"descargar::{filename}"))
        conn.commit()

        return jsonify({"mensaje": "Archivo subido correctamente"}), 200
    except Exception as e:
        conn.rollback()
        return f"Error al guardar archivo: {e}", 500

@app.route('/descargas/<filename>', methods=['GET'])
def descargar_archivo(filename):
    ruta = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    if not os.path.exists(ruta):
        return f"Archivo '{filename}' no encontrado", 404
    try:
        def eliminar_despues(response):
            try:
                os.remove(ruta)
            except Exception:
                pass
            return response

        response = send_file(ruta, as_attachment=True)
        response.call_on_close(lambda: eliminar_despues(response))
        return response
    except Exception as e:
        return f"Error al servir archivo: {e}", 500

@app.route('/archivo/<nombre_pc>', methods=['POST'])
def subir_url_archivo(nombre_pc):
    data = request.get_json()
    url = data.get("url")
    if not url:
        return jsonify({"error": "Falta la URL"}), 400
    try:
        cursor.execute(
            "INSERT INTO archivos_pendientes (nombre, url) VALUES (%s, %s);",
            (nombre_pc, url)
        )
        conn.commit()
        print(f"URL de archivo recibida para {nombre_pc}: {url}")
        return jsonify({"mensaje": "Archivo registrado para descarga"})
    except Exception as e:
        conn.rollback()
        return jsonify({"error": str(e)}), 500

@app.route('/archivo/<nombre_pc>', methods=['GET'])
def obtener_url_archivo(nombre_pc):
    try:
        cursor.execute(
            "SELECT url FROM archivos_pendientes WHERE nombre = %s ORDER BY rowid ASC LIMIT 1;",
            (nombre_pc,)
        )
        resultado = cursor.fetchone()
        if resultado:
            url = resultado[0]
            cursor.execute(
                "DELETE FROM archivos_pendientes WHERE nombre = %s AND url = %s;",
                (nombre_pc, url)
            )
            conn.commit()
            print(f"Entregando archivo pendiente a {nombre_pc}: {url}")
            return jsonify({"url": url})
        else:
            return jsonify({"url": None})
    except Exception as e:
        conn.rollback()
        return jsonify({"error": str(e)}), 500

@app.route('/limpiar/<nombre_pc>', methods=['POST'])
def limpiar_datos(nombre_pc):
    try:
        cursor.execute("DELETE FROM comandos WHERE nombre = %s;", (nombre_pc,))
        cursor.execute("DELETE FROM archivos_pendientes WHERE nombre = %s;", (nombre_pc,))
        conn.commit()
        print(f"Datos limpiados para {nombre_pc}")
        return jsonify({"mensaje": f"Comandos y archivos limpiados para {nombre_pc}"})
    except Exception as e:
        conn.rollback()
        return jsonify({"error": str(e)}), 500

@app.errorhandler(RequestEntityTooLarge)
def handle_large_file(error):
    return "Archivo demasiado grande", 413

@app.route('/archivo_chunk/<nombre>', methods=['POST'])
def recibir_chunk(nombre):
    chunk = request.files.get('chunk')
    index = request.form.get('index')
    total = request.form.get('total')
    filename = request.form.get('filename')

    ruta = os.path.join(app.config['UPLOAD_FOLDER'], f"{nombre}_{filename}")
    with open(ruta, 'ab') as f:
        f.write(chunk.read())

    if int(index) + 1 == int(total):
        print(f"Archivo {filename} de {nombre} recibido completo.")
        cursor.execute("""
            INSERT INTO comandos (nombre, accion) VALUES (%s, %s)
            ON CONFLICT (nombre) DO UPDATE SET accion = EXCLUDED.accion;
        """, (nombre, f"descargar::{nombre}_{filename}"))
        conn.commit()

    return jsonify({"estado": "chunk recibido"}), 200
