from flask import Flask, request, render_template ,jsonify

app = Flask(__name__) #使用flask创建这个对象 name表示当前模块名 代表app.py这个模块
class User:
    def __init__(self, name, email): #self表示当前对象，实例本身。可以访问他的属性
        self.name = name
        self.email = email
#创建路由和视图映射

@app.route('/')#/表示根路由 使用下面这个函数
def hello_world():
    user =User('zhangsan', 'zhangsan@163.com')

    return render_template("demo1.html",user=user)#返回html页面 默认会去templates目录下寻找index.html文件"

#1 debug=True表示开启调试模式
# 当代码有修改时，flask会自动重启服务器 一改就会自动加载 方便调试

#2 host 设置host=0.0.0.0 就可以在局域网内访问我的ip4即可

#3 port 设置端口号 默认是5000 可以设置成其他端口号

#http默认80端口，https默认443端口



@app.route("/demo/<id>")
def demo(id):
    return render_template("demo.html",id=id)

@app.route("/demo2", methods=["POST",'GET']) #都可以
def demo2():
    id=request.args.get("id",default=1,type=str)           #类字典类型，get请求
    id1=request.form.get("id1")
    print(request.jason) #jason数据格式
    return f"demo2{id}" #return jsonify({"id":id,"id1":id1}) #返回json数据格式
@app.route("/filter")
def filter_demo():
    user =User('zhangsan', 'zhangsan@163.com')
    return render_template("filter.html",user=user)

@app.route("/child1")
def child1():
    return render_template("child1.html")

if __name__ == '__main__':
    app.run(debug=True,host='0.0.0.0',port=8000) #打开debug模式  端口被别的占用之类的  