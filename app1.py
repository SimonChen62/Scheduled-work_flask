from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import text
from flask_migrate import Migrate


app = Flask(__name__)

HOSTNAME="localhost"  # 数据库主机名
PORT="3306"  # 数据库端口号
USERNAME="root"  # 数据库用户名
PASSWORD="Xajdlyld6622"
DATABASE="flasklearn"  # 数据库名称
app.config['SQLALCHEMY_DATABASE_URI'] = 'mysql+pymysql://{}:{}@{}:{}/{}?charset=utf8mb4'.format(USERNAME,PASSWORD,HOSTNAME,PORT,DATABASE)


#在app.config中添加数据库的配置信息 
#sqlalchemy会自动读取config中数据库的信息

db = SQLAlchemy(app)

migrate = Migrate(app, db)  #初始化迁移对象

#orm映射三个步骤 在终端执行
#flask db init

#测试连接
#with app.app_context(): #创建 Flask 应用上下文
#    with db.engine.connect() as conn: #从 SQLAlchemy 数据库引擎获取一个数据库连接
#        rs = conn.execute(text("SELECT 1")) 
#        print(rs.fetchone())

class User(db.Model):
    __tablename__ = 'user'
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)  #表当中的字段，主键/像索引，自动递增
    username = db.Column(db.String(80), unique=True, nullable=False) #不能为空，而且唯一
    password = db.Column(db.String(120), unique=True, nullable=False)

    #articles= db.relationship('Article', back_populates='author')  #一对多关系，反向引用


class Article(db.Model):
    __tablename__ = 'article'
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)  #表当中的字段，主键/像索引，自动递增
    title = db.Column(db.String(200), unique=True, nullable=False) #不能为空，而且唯一
    content = db.Column(db.Text,  nullable=False) #string最多255
    #添加外键
    author_id=db.Column(db.Integer,db.ForeignKey('user.id')) #外键，关联user表的id 关联而已，需要外显写
    author = db.relationship('User',backref='authors') #反向引用




with app.app_context():
    db.create_all()  #创建所有表，修改class字段就无法自动更新，需要手动删除表再创建 

@app.route('/')
def hello_world():
    return "Hello, world!"

@app.route('/add_user') #添加用户   
def add_user():
    user = User(username='testuser1',password='11')
    db.session.add(user)  #添加
    db.session.commit()   #同步到数据库
    return "添加成功"

@app.route('/query_user') #查询用户
def query_user():#get请求
    user=User.query.get(1) #get是根据主键查找
    if user:
        print(f"{user.id}:{user.username}-{user.password}")  #打印用户名和密码
        return f"{user.id}:{user.username}-{user.password}"
    else:
        return "用户不存在"

@app.route('/query_user1') #查询用户
@app.route('/query_user1') #查询用户
def query_user1():#get请求
    user=User.query.filter_by(username='testuser1').first() # 获取第一个匹配的结果
    if user:  # 现在 user 是具体的用户对象或 None
        print(f"{user.id}:{user.username}-{user.password}")  #打印用户名和密码
        return f"{user.id}:{user.username}-{user.password}"
    else:
        return "用户不存在"
    
@app.route('/user_update')
def user_update():
    users=User.query.filter_by(username='testuser1').first() #返回user对象，而不是之前的类数组
    users.password="112"
    db.session.commit()
    return "更新成功"

@app.route('/user_delete')
def user_delete():
    users=User.query.filter_by(username='testuser1').first() #User.query.get(1)
    db.session.delete(users)
    db.session.commit()
    return "删除成功"

@app.route('/add_article')
def add_article():
    article = Article(title='测试文章1',content='测试内容1')
    article.author=User.query.get(1)

    db.session.add(article)
    db.session.commit()
    return "添加文章成功"

@app.route('/query_article')
def query_article():
    user=User.query.get(1)
    for article in user.authors:  #反向引用
        print(f"{article.id}:{article.title}-{article.content}")
    return "查询文章成功"
# 在if __name__ == '__main__':前面添加
app.config['FLASK_APP'] = __name__

if __name__ == '__main__':
    app.run(debug=True)