from flask import Flask, request, jsonify, render_template_string
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

# === Página principal con listado de PCs y opción de eliminación ===
HTML_TEMPLATE = """
<!doctype html>
<html lang="es">
  <head>
    <meta charset="utf-8">
    <title>ControlPC</title>
  </head>
  <body>
    <h1>Servidor de ControlPC activo</h1>
    <h2>Equipos registrados</h2>
    <ul>
      {% for nombre, ip in pcs %}
        <li>
          {{ nombre }} - {{ ip }}
          <form method="POST" action="/eliminar/{{ nombre }}" style="display:inline;">
            <input type="password" name="clave" placeholder="Contraseña" required>
            <button type="submit">Eliminar</button>
          </form>
        </li>
      {% endfor %}
    </ul>
  </body>
</html>
"""

@app.route('/')
def inicio():
    cursor.execute("SELECT nombre, ip FROM pcs;")
    pcs = cursor.fetchall()
    return render_template_string(HTML_TEMPLATE, pcs=pcs)

@app.route('/eliminar/<nombre>', methods=['POST'])
def eliminar_pc(nombre):
    clave = request.form.get("clave")
    if clave == "admin123":  # Cambia esta contraseña por una más segura
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

if __name__ == '__main__':
    app.run(debug=True)
