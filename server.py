from flask import Flask, request, jsonify, render_template_string, redirect, url_for, send_from_directory
import psycopg2
import os
import socket
import time
from datetime import datetime, timedelta
import requests

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
        conn.commit()
        return jsonify({"accion": None})
    except Exception as e:
        conn.rollback()
        return jsonify({"error": str(e)}), 500

@app.route('/archivo/<nombre>', methods=['POST'])
def enviar_archivo_a_pc(nombre):
    archivo = request.files.get('archivo')
    if not archivo:
        return "No se envió ningún archivo", 400

    try:
        # Buscar la IP del nombre de PC en la base de datos
        cursor.execute("SELECT ip FROM pcs WHERE nombre = %s;", (nombre,))
        resultado = cursor.fetchone()

        if not resultado:
            return "PC no registrada", 404

        ip_destino = resultado[0]
        url = f"http://{ip_destino}:5000/recibir_archivo"

        # Preparar el archivo para reenviarlo a la PC destino
        archivos = {'archivo': (archivo.filename, archivo.stream, archivo.mimetype)}
        respuesta = requests.post(url, files=archivos)

        if respuesta.status_code == 200:
            return "Archivo reenviado correctamente", 200
        else:
            return f"Error al reenviar archivo: {respuesta.text}", 500

    except Exception as e:
        return f"Error del servidor intermedio: {e}", 500


if __name__ == '__main__':
    app.run(debug=True)
