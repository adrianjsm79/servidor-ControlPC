from flask import Flask, request, jsonify, render_template_string
import psycopg2
import os
import socket
import time

app = Flask(__name__)

# === Conexión a la base de datos ===
DATABASE_URL = os.getenv("DATABASE_URL")
conn = psycopg2.connect(DATABASE_URL, sslmode='require')
cursor = conn.cursor()

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

# === Página principal con listado de PCs y opción de eliminación ===
HTML_TEMPLATE = """
<!doctype html>
<html lang="es">
  <head>
    <meta charset="utf-8">
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
    </style>
    <script>
      function solicitarClave(nombre) {
        const clave = prompt("Ingresa la contraseña para eliminar a: " + nombre);
        if (clave !== null) {
          const form = document.createElement('form');
          form.method = 'POST';
          form.action = `/eliminar/${nombre}`;

          const input = document.createElement('input');
          input.type = 'hidden';
          input.name = 'clave';
          input.value = clave;

          form.appendChild(input);
          document.body.appendChild(form);
          form.submit();
        }
      }
    </script>
  </head>
  <body onload="setTimeout(() => location.reload(), 10000)">
    <h1>Servidor de ControlPC activo</h1>
    <h2>Equipos registrados</h2>
    <ul>
      {% for nombre, ip in pcs %}
        <li>
          <span><span class="estado {{ estados[nombre] }}">{{ estados[nombre] }}</span>{{ nombre }} - {{ ip }}</span>
          <button onclick="solicitarClave('{{ nombre }}')">Eliminar</button>
        </li>
      {% endfor %}
    </ul>
  </body>
</html>
"""

@app.route('/')
def inicio():
    try:
        cursor.execute("SELECT nombre, ip FROM pcs;")
        pcs = cursor.fetchall()
        estados = {}
        for nombre, ip in pcs:
            try:
                socket.create_connection((ip, 5000), timeout=1)
                estados[nombre] = "conectado"
            except:
                estados[nombre] = "desconectado"
        return render_template_string(HTML_TEMPLATE, pcs=pcs, estados=estados)
    except Exception as e:
        return f"<h1>Error en el servidor</h1><p>{e}</p>", 500

@app.route('/eliminar/<nombre>', methods=['POST'])
def eliminar_pc(nombre):
    clave = request.form.get("clave")
    if clave == "admin123":
        cursor.execute("DELETE FROM pcs WHERE nombre = %s;", (nombre,))
        cursor.execute("DELETE FROM comandos WHERE nombre = %s;", (nombre,))
        conn.commit()
        return f"PC '{nombre}' eliminada. <a href='/'>Volver</a>"
    else:
        return "Contraseña incorrecta. <a href='/'>Volver</a>", 403

@app.route('/registrar', methods=['POST'])
def registrar_pc():
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
    try:
        cursor.execute("BEGIN;")
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
