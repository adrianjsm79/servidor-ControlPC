from flask import Flask, request, jsonify, render_template_string, redirect, url_for, send_from_directory
import psycopg2
from werkzeug.utils import secure_filename
import os
import socket
import time
from datetime import datetime, timedelta
import requests
import shutil
import threading
#Flask es el framework principal del servidor, 
#request y jsonify para manejar datos entrantes y datos formato json
#sendfromdirectory para descargas
#sqlalchemy para mapear las clases, tablas y la base de datos en general
#threading para manejar tareas por hilos
#etc etc etc

#esta es lacarpeta donde se guardaran los archivos temporales
#de los archivos subidos
UPLOAD_FOLDER = "archivos_temporales"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

#Conexión a la base de datos postgresql en render
DATABASE_URL = os.getenv("DATABASE_URL")
conn = psycopg2.connect(DATABASE_URL, sslmode='require')
cursor = conn.cursor()

#Intentar agregar columna de ultima actividad si no existe
try:
    cursor.execute("ALTER TABLE pcs ADD COLUMN ultima_actividad TIMESTAMP DEFAULT NOW();")
    conn.commit()
except psycopg2.errors.DuplicateColumn:
    conn.rollback()

#Crear tablas si no existen
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

#HTML para la interfaz del control del servidor 
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

@app.route('/') #esta es la ruta principal, muestra pcs y estado
def inicio():
    try:
        cursor.execute("SELECT nombre, ip, ultima_actividad FROM pcs;")
        pcs = cursor.fetchall()
        ahora = datetime.utcnow()
        estados = {}
        resultado = [(nombre, ip) for nombre, ip, _ in pcs]
        #se calcula si una pc está conectada por la ultima actividad
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

#endpoint pa actualizar la actividad de la pc (que es llamado por la pc cada x tiempo)
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

#elimina pc (ocupa contraseña) desde el html del server
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

#endpoint que registra las pc
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
        ruta = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        archivo.save(ruta)

        cursor.execute("""
            INSERT INTO comandos (nombre, accion) VALUES (%s, %s)
            ON CONFLICT (nombre) DO UPDATE SET accion = EXCLUDED.accion;
        """, (nombre, f"descargar::{filename}"))
        conn.commit()

        return jsonify({"mensaje": "Archivo subido correctamente"}), 200
    except Exception as e:
        conn.rollback()  # <-- Agrega rollback aquí
        return f"Error al guardar archivo: {e}", 500

@app.route('/descargas/<filename>', methods=['GET'])
def descargar_archivo(filename):
    try:
        ruta = os.path.join(app.config['UPLOAD_FOLDER'], filename)

        # Verificamos que el archivo existe
        if not os.path.exists(ruta):
            return f"Archivo '{filename}' no encontrado", 404

        # Leemos el archivo completo en memoria para poder borrarlo luego
        with open(ruta, 'rb') as f:
            contenido = f.read()

        # Eliminamos el archivo después de leerlo
        os.remove(ruta)

        # Devolvemos el archivo leído manualmente with los headers correctos
        from flask import Response
        return Response(
            contenido,
            headers={
                'Content-Disposition': f'attachment; filename={filename}',
                'Content-Type': 'application/octet-stream'
            }
        )

    except Exception as e:
        return f"Error al servir y eliminar archivo: {e}", 500

CHUNK_UPLOAD_FOLDER = os.path.join(UPLOAD_FOLDER, 'temp')
os.makedirs(CHUNK_UPLOAD_FOLDER, exist_ok=True)

@app.route('/upload_chunk', methods=['POST'])
def upload_chunk():
    chunk = request.files.get('chunk')
    chunk_index = request.form.get('chunkIndex')
    filename = request.form.get('filename')
    destino = request.form.get('destino')  # <- nombre de la PC destino

    if not chunk or chunk_index is None or not filename or not destino:
        return "Faltan datos", 400

    # Guardamos los chunks por destino/archivo, para evitar conflictos
    chunk_folder = os.path.join(CHUNK_UPLOAD_FOLDER, destino, filename)
    os.makedirs(chunk_folder, exist_ok=True)

    chunk_path = os.path.join(chunk_folder, f'chunk_{chunk_index}.part')
    chunk.save(chunk_path)
    return "OK", 200


@app.route('/complete_upload', methods=['POST'])
def complete_upload():
    filename = request.form.get('filename')
    destino = request.form.get('destino')  # nombre de la PC destino

    if not filename or not destino:
        return "Faltan datos", 400

    chunk_folder = os.path.join(CHUNK_UPLOAD_FOLDER, destino, filename)
    final_path = os.path.join(UPLOAD_FOLDER, filename)

    try:
        # Ensamblamos el archivo
        with open(final_path, 'wb') as f_out:
            chunks = sorted(
                os.listdir(chunk_folder),
                key=lambda x: int(x.split('_')[1].split('.')[0])
            )
            for chunk_file in chunks:
                with open(os.path.join(chunk_folder, chunk_file), 'rb') as f_in:
                    f_out.write(f_in.read())

        # Limpiamos los chunks
        shutil.rmtree(chunk_folder)

        # Enviamos el comando para que la PC lo descargue
        cursor.execute("""
            INSERT INTO comandos (nombre, accion)
            VALUES (%s, %s)
            ON CONFLICT (nombre) DO UPDATE SET accion = EXCLUDED.accion;
        """, (destino, f"descargar::{filename}"))
        conn.commit()

        return "Upload complete", 200
    except Exception as e:
        conn.rollback()
        return f"Error al ensamblar archivo: {e}", 500


def limpiar_archivos_antiguos():
    while True:
        ahora = time.time()

        # Limpiar archivos ensamblados antiguos
        for archivo in os.listdir(UPLOAD_FOLDER):
            ruta = os.path.join(UPLOAD_FOLDER, archivo)
            if os.path.isfile(ruta) and ahora - os.path.getmtime(ruta) > 900:
                try:
                    os.remove(ruta)
                except Exception:
                    pass

        # Limpiar carpetas de chunks por destino
        for destino in os.listdir(CHUNK_UPLOAD_FOLDER):
            ruta_destino = os.path.join(CHUNK_UPLOAD_FOLDER, destino)
            if os.path.isdir(ruta_destino):
                for carpeta_archivo in os.listdir(ruta_destino):
                    ruta_carpeta = os.path.join(ruta_destino, carpeta_archivo)
                    if os.path.isdir(ruta_carpeta) and ahora - os.path.getmtime(ruta_carpeta) > 900:
                        try:
                            shutil.rmtree(ruta_carpeta)
                        except Exception:
                            pass

        time.sleep(600)


# Inicia el hilo de limpieza en segundo plano
threading.Thread(target=limpiar_archivos_antiguos, daemon=True).start()
