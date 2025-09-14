from flask import Flask, request, jsonify, session
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import text, exc
from flask_migrate import Migrate
from flask_cors import CORS
import os
import logging
from werkzeug.security import generate_password_hash, check_password_hash
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.triggers.cron import CronTrigger
from datetime import datetime
import subprocess
from werkzeug.utils import secure_filename
import time
import signal

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- 部署配置 ---
FRONTEND_URL = os.environ.get('FRONTEND_URL', 'http://127.0.0.1:3000')
DATABASE_URL = os.environ.get('DATABASE_URL')
SECRET_KEY = os.environ.get('SECRET_KEY', 'dev-secret-key')

app = Flask(__name__)

# --- 数据库配置 ---
if DATABASE_URL:
    if DATABASE_URL.startswith("postgres://"):
        # 处理 Heroku/Render 的 PostgreSQL SSL 问题
        app.config['SQLALCHEMY_DATABASE_URI'] = DATABASE_URL.replace("postgres://", "postgresql://", 1)
        # 添加 SSL 配置以解决 "decryption failed or bad record mac" 错误
        if "?sslmode=" not in app.config['SQLALCHEMY_DATABASE_URI']:
            app.config['SQLALCHEMY_DATABASE_URI'] += "?sslmode=require"
    elif DATABASE_URL.startswith("mysql://"):
        app.config['SQLALCHEMY_DATABASE_URI'] = DATABASE_URL.replace("mysql://", "mysql+pymysql://", 1)
    else:
        app.config['SQLALCHEMY_DATABASE_URI'] = DATABASE_URL
    logger.info(f"使用生产数据库: {app.config['SQLALCHEMY_DATABASE_URI']}")
else:
    HOSTNAME = "localhost"
    PORT = "3306"
    USERNAME = "root"
    PASSWORD = "Xajdlyld6622"
    DATABASE = "flasklearn"
    app.config['SQLALCHEMY_DATABASE_URI'] = f'mysql+pymysql://{USERNAME}:{PASSWORD}@{HOSTNAME}:{PORT}/{DATABASE}?charset=utf8mb4'
    logger.info("使用本地开发数据库")

app.config['SECRET_KEY'] = SECRET_KEY

# 添加数据库连接池配置以提高稳定性
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
    'pool_pre_ping': True,
    'pool_recycle': 300,
    'pool_timeout': 900,
    'max_overflow': 0
}

# --- Session 和 CORS 配置 ---
if DATABASE_URL:
    app.config['SESSION_COOKIE_SAMESITE'] = 'None'
    app.config['SESSION_COOKIE_SECURE'] = True
    CORS(app, origins=FRONTEND_URL, supports_credentials=True,
         allow_headers=["Content-Type", "Authorization"],
         methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"])
else:
    app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
    app.config['SESSION_COOKIE_SECURE'] = False
    app.config['SESSION_COOKIE_HTTPONLY'] = True
    CORS(app, origins=FRONTEND_URL, supports_credentials=True)

# --- 文件上传配置 ---
UPLOAD_BASE = os.path.abspath('uploads')
os.makedirs(UPLOAD_BASE, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_BASE
logger.info(f"上传目录设置为: {UPLOAD_BASE}")

# 添加健康检查路由
@app.route('/')
def health_check():
    return jsonify({"status": "ok", "message": "Server is running"}), 200

# 添加数据库健康检查路由
@app.route('/health')
def health():
    try:
        db.session.execute(text('SELECT 1'))
        return jsonify({"status": "healthy", "database": "connected"}), 200
    except Exception as e:
        return jsonify({"status": "unhealthy", "error": str(e)}), 500

db = SQLAlchemy(app)
migrate = Migrate(app, db)

# --- 数据模型 ---
class User(db.Model):
    __tablename__ = 'user'
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password = db.Column(db.String(300), nullable=False)

class Task(db.Model):
    __tablename__ = 'task'
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    task_name = db.Column(db.String(100), nullable=False)
    script_path = db.Column(db.String(255), nullable=False)
    cron_expr = db.Column(db.String(50), nullable=False)
    status = db.Column(db.String(20), default='stopped')
    created_at = db.Column(db.DateTime, default=datetime.now)
    user = db.relationship('User', backref=db.backref('tasks', lazy=True))

# --- 调度器初始化 ---
scheduler = BackgroundScheduler()
scheduler.add_jobstore(SQLAlchemyJobStore(url=app.config['SQLALCHEMY_DATABASE_URI']), 'default')

def start_scheduler():
    max_retries = 3
    for attempt in range(max_retries):
        try:
            # 测试数据库连接
            db.session.execute(text('SELECT 1'))
            logger.info("数据库连接成功")

            # 启动调度器
            if not scheduler.running:
                scheduler.start()
                logger.info("调度器已成功启动")
            else:
                logger.info("调度器已在运行中")
            return
        except Exception as e:
            logger.error(f"调度器启动失败 (尝试 {attempt + 1}/{max_retries}): {str(e)}")
            if attempt < max_retries - 1:
                time.sleep(2)  # 等待2秒后重试
            else:
                raise

# 在应用上下文中启动调度器
with app.app_context():
    try:
        start_scheduler()
    except Exception as e:
        logger.fatal(f"调度器初始化失败，程序无法继续运行: {str(e)}")

# --- 调试接口 ---
@app.route('/debug/scheduler')
def debug_scheduler():
    return jsonify({
        "running": scheduler.running,
        "job_count": len(scheduler.get_jobs()),
        "jobs": [j.id for j in scheduler.get_jobs()]
    })

# --- 路由定义 ---
@app.route('/register', methods=['POST'])
def register():
    try:
        data = request.get_json()
        if not data:
            return jsonify({"error": "请求体不能为空"}), 400

        username = data.get('username')
        password = data.get('password')

        if not username or not password:
            return jsonify({"error": "用户名和密码不能为空"}), 400

        existing_user = User.query.filter(User.username == username).first()
        if existing_user:
            return jsonify({"error": "用户名已存在"}), 400

        hashed_password = generate_password_hash(password)
        new_user = User(username=username, password=hashed_password)
        db.session.add(new_user)
        db.session.commit()

        logger.info(f"用户注册成功: {username}")
        return jsonify({"message": "注册成功"}), 201

    except exc.SQLAlchemyError as e:
        logger.error(f"数据库错误: {str(e)}")
        return jsonify({"error": "数据库操作失败"}), 500
    except Exception as e:
        logger.error(f"注册过程中发生错误: {str(e)}")
        return jsonify({"error": "服务器内部错误"}), 500

@app.route('/login', methods=['POST'])
def login():
    try:
        data = request.get_json()
        if not data:
            return jsonify({'error': '请求体不能为空'}), 400

        username = data.get('username')
        password = data.get('password')

        if not username or not password:
            return jsonify({'error': '用户名和密码不能为空'}), 400

        user = User.query.filter(User.username == username).first()
        if user and check_password_hash(user.password, password):
            user_info = {'id': user.id, 'username': user.username}
            session['user_id'] = user.id
            logger.info(f"用户登录成功: {username}")
            return jsonify({'message': '登录成功', 'user': user_info}), 200
        else:
            return jsonify({'error': '用户名或密码错误'}), 401

    except Exception as e:
        logger.error(f"登录过程中发生错误: {str(e)}")
        return jsonify({'error': '服务器内部错误'}), 500

@app.route('/upload_task', methods=['POST'])
def upload_task():
    try:
        if 'user_id' not in session:
            return jsonify({'error': '请先登录'}), 401

        if 'script' not in request.files:
            return jsonify({'error': '未提供脚本文件'}), 400

        file = request.files['script']
        if file.filename == '':
            return jsonify({'error': '文件名为空'}), 400

        filename = secure_filename(file.filename)
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(filepath)

        logger.info(f"文件上传成功: {filepath}")
        return jsonify({"message": "上传成功", "script_path": filepath}), 200

    except Exception as e:
        logger.error(f"文件上传失败: {str(e)}")
        return jsonify({"error": "文件上传失败"}), 500

@app.route('/create_task', methods=['POST'])
def create_task():
    try:
        if 'user_id' not in session:
            return jsonify({'error': '请先登录'}), 401

        data = request.get_json()
        if not data:
            return jsonify({'error': '请求体不能为空'}), 400

        user_id = session['user_id']
        cron_expression = data.get('cron_expr')

        # 验证 cron 表达式
        try:
            CronTrigger.from_crontab(cron_expression)
        except Exception as e:
            logger.warning(f"无效的cron表达式: {cron_expression}, 错误: {str(e)}")
            return jsonify({"error": f"无效的cron表达式: {str(e)}"}), 400

        new_task = Task(
            user_id=user_id,
            task_name=data['task_name'],
            script_path=data['script_path'],
            cron_expr=cron_expression
        )
        db.session.add(new_task)
        db.session.commit()

        logger.info(f"任务创建成功: {data['task_name']}")
        return jsonify({"message": "任务创建成功", "task_id": new_task.id}), 201

    except Exception as e:
        logger.error(f"任务创建失败: {str(e)}")
        return jsonify({"error": "任务创建失败"}), 500

def run_script(script_path, task_name):
    try:
        if not os.path.exists(script_path):
            logger.error(f"脚本文件不存在: {script_path}")
            return False

        logger.info(f"开始执行任务: {task_name}")
        result = subprocess.run(
            ['python', script_path],
            capture_output=True,
            text=True,
            check=True
        )
        logger.info(f"任务 '{task_name}' 执行成功. 输出: {result.stdout}")
        return True
    except FileNotFoundError:
        logger.error(f"Python 可执行文件未找到")
        return False
    except subprocess.CalledProcessError as e:
        logger.error(f"任务 '{task_name}' 执行失败. 错误: {e.stderr}")
        return False
    except Exception as e:
        logger.error(f"执行任务 '{task_name}' 时发生未知错误: {str(e)}")
        return False

@app.route('/start/<int:task_id>', methods=['POST'])
def start_task(task_id):
    try:
        if 'user_id' not in session:
            return jsonify({"error": "请先登录"}), 401

        task = Task.query.filter(Task.id == task_id, Task.user_id == session['user_id']).first()
        if not task:
            return jsonify({"error": "任务未找到"}), 404

        # 检查脚本是否存在
        if not os.path.exists(task.script_path):
            logger.error(f"脚本文件不存在: {task.script_path}")
            return jsonify({"error": "脚本文件不存在"}), 400

        # 解析 cron 表达式
        try:
            trigger = CronTrigger.from_crontab(task.cron_expr)
        except Exception as e:
            logger.error(f"无法解析cron表达式: {task.cron_expr}, 错误: {str(e)}")
            return jsonify({"error": f"无法解析cron表达式: {str(e)}"}), 400

        # 添加任务到调度器
        try:
            scheduler.add_job(
                run_script,
                trigger,
                args=[task.script_path, task.task_name],
                id=str(task_id),
                replace_existing=True
            )
            logger.info(f"任务已添加到调度器: {task.task_name}")
            
            # 更新状态
            task.status = 'running'
            db.session.commit()
            logger.info(f"任务状态更新为 running: {task.task_name}")
            
            return jsonify({"message": "任务已启动", "status": "running"}), 200
            
        except Exception as e:
            logger.error(f"添加任务到调度器失败: {str(e)}")
            return jsonify({"error": "添加任务失败"}), 500

    except Exception as e:
        logger.error(f"任务启动失败: {str(e)}")
        return jsonify({"error": "任务启动失败，请检查数据库连接"}), 500

@app.route('/stop/<int:task_id>', methods=['POST'])
def stop_task(task_id):
    try:
        if 'user_id' not in session:
            return jsonify({"error": "请先登录"}), 401

        task = Task.query.filter(Task.id == task_id, Task.user_id == session['user_id']).first()
        if not task:
            return jsonify({"error": "任务不存在"}), 404

        job = scheduler.get_job(str(task_id))
        if job:
            scheduler.remove_job(str(task_id))
            logger.info(f"任务已停止: {task.task_name}")

        task.status = 'stopped'
        db.session.commit()
        return jsonify({"message": "任务已停止"}), 200

    except Exception as e:
        logger.error(f"任务停止失败: {str(e)}")
        return jsonify({"error": "任务停止失败"}), 500

@app.route('/get-task', methods=['GET'])
def get_task():
    try:
        if 'user_id' not in session:
            return jsonify({"error": "请先登录"}), 401

        tasks = Task.query.filter(Task.user_id == session['user_id']).all()
        task_list = [{
            "id": task.id,
            "task_name": task.task_name,
            "script_path": task.script_path,
            "cron_expr": task.cron_expr,
            "status": task.status,
            "created_at": task.created_at.strftime("%Y-%m-%d %H:%M:%S")
        } for task in tasks]

        return jsonify({"tasks": task_list}), 200

    except Exception as e:
        logger.error(f"获取任务列表失败: {str(e)}")
        return jsonify({"error": "获取任务列表失败"}), 500

@app.route('/api/check-auth', methods=['GET'])
def check_auth():
    if 'user_id' in session:
        user = User.query.get(session['user_id'])
        if user:
            return jsonify({
                'isAuthenticated': True,
                'user': {'id': user.id, 'username': user.username}
            }), 200
    return jsonify({'isAuthenticated': False}), 401

if __name__ == '__main__':
    with app.app_context():
        try:
            db.create_all()
        except Exception as e:
            logger.error(f"数据库初始化失败: {str(e)}")

    app.run(host='127.0.0.1', port=5000, debug=True)