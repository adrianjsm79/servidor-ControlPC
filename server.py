from flask import Flask, request, jsonify, render_template_string
import psycopg2
import os
import socket
import time
from datetime import datetime, timedelta

app = Flask(__name__)

# === Conexión a la base de datos ===
DATABASE_URL = os.getenv("DATABASE_URL")
conn = psycopg2.connect(DATABASE_URL, sslmode='require')
cursor = conn.cursor()

# === Intentar agregar columna si no existe ===
try:
    cursor.execute("ALTER TABLE pcs ADD COLUMN ultima_actividad TIMESTAMP DEFAULT NOW();")
    conn.commit()
except psycopg2.errors.DuplicateColumn:
    conn.rollback()  # Ya existe la columna, ignoramos

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

# === Plantilla HTML con recarga y estados de PCs ===
HTML_TEMPLATE = """
<!doctype html>
<html lang=\"es\">
  <head>
    <meta charset=\"utf-8\">
    <title>ControlPC</title>
    <style>
      body {
        font-family: Arial, sans-serif;
        margin: 20px;
        background-color: #f4f4f4;
        color: #333;
      }
      h1, h2 {
        color: #222;
      }
      ul {
        list-style: none;
        padding: 0;
      }
      li {
        background: #fff;
        margin: 10px 0;
        padding: 10px;
        border: 1px solid #ccc;
        border-radius: 6px;
        display: flex;
        justify-content: space-between;
        align-items: center;
      }
      .estado {
        font-size: 0.9em;
        padding: 2px 6px;
        border-radius: 4px;
        background-color: #ccc;
        color: #fff;
        margin-right: 10px;
      }
      .conectado {
        background-color: #2ecc71;
      }
      .desconectado {
        background-color: #e67e22;
      }
      button {
        background-color: #e74c3c;
        color: white;
        border: none;
        padding: 5px 10px;
        border-radius: 4px;
        cursor: pointer;
      }
      #modal {
        display: none;
        position: fixed;
        top: 0;
        left: 0;
        width: 100%;
        height: 100%;
        background: rgba(0, 0, 0, 0.5);
        justify-content: center;
        align-items: center;
      }
      #modalContent {
        background: white;
        padding: 20px;
        border-radius: 6px;
        text-align: center;
      }
      #modalContent input {
        padding: 6px;
        margin-top: 10px;
        margin-bottom: 10px;
        width: 80%;
      }
    </style>
    <script>
      let pcSeleccionada = "";
      function solicitarClave(nombre) {
        pcSeleccionada = nombre;
        document.getElementById('modal').style.display = 'flex';
        document.getElementById('claveInput').value = "";
      }

      function cerrarModal() {
        document.getElementById('modal').style.display = 'none';
      }

      function enviarClave() {
        const clave = document.getElementById('claveInput').value;
        const form = document.createElement('form');
        form.method = 'POST';
        form.action = `/eliminar/${pcSeleccionada}`;

        const input = document.createElement('input');
        input.type = 'hidden';
        input.name = 'clave';
        input.value = clave;

        form.appendChild(input);
        document.body.appendChild(form);
        form.submit();
      }

      // Recarga la página cada 10 segundos
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

    <!-- Modal -->
    <div id=\"modal\" onclick=\"if(event.target === this) cerrarModal()\">
      <div id=\"modalContent\">
        <h3>Ingresa la contraseña</h3>
        <input id=\"claveInput\" type=\"password\" placeholder=\"Contraseña\">
        <br>
        <button onclick=\"enviarClave()\">Confirmar</button>
        <button onclick=\"cerrarModal()\">Cancelar</button>
      </div>
    </div>

    {% if mensaje %}
    <script>
      alert("{{ mensaje }}");
    </script>
    {% endif %}
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
        return render_template_string(HTML_TEMPLATE, pcs=resultado, estados=estados, mensaje=request.args.get('mensaje'))
    except Exception as e:
        conn.rollback()
        return f"<h1>Error en el servidor</h1><p>{e}</p>", 500

@app.route('/eliminar/<nombre>', methods=['POST'])
def eliminar_pc(nombre):
    clave = request.form.get("clave")
    if clave != "admin123":
        return ("", 302, {"Location": f"/?mensaje=Contrase%C3%B1a%20incorrecta"})
    try:
        cursor.execute("SELECT ultima_actividad FROM pcs WHERE nombre = %s;", (nombre,))
        resultado = cursor.fetchone()
        if resultado:
            ultima = resultado[0]
            if ultima and datetime.utcnow() - ultima < timedelta(seconds=15):
                return ("", 302, {"Location": f"/?mensaje=No%20puedes%20eliminar%20una%20PC%20activa"})
        cursor.execute("DELETE FROM pcs WHERE nombre = %s;", (nombre,))
        cursor.execute("DELETE FROM comandos WHERE nombre = %s;", (nombre,))
        conn.commit()
        return ("", 302, {"Location": f"/?mensaje=PC%20'{nombre}'%20eliminada%20correctamente"})
    except Exception as e:
        conn.rollback()
        return ("", 302, {"Location": f"/?mensaje=Error%20al%20eliminar:%20{str(e)}"})

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
    cursor.execute("SELECT nombre, ip FROM pcs;")
    pcs = cursor.fetchall()
    return jsonify([{ "nombre": nombre, "ip": ip } for nombre, ip in pcs])

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
        return jsonify({"ip_destino": ip, "accion": accion, "estado": "pendiente"})
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

if __name__ == '__main__':
    app.run(debug=True)
