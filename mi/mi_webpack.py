# webpack应用专用的脚本，扒js之类的

from etc.base import *
import re
import time
import requests
from mitmproxy import http
from etc.jsast import AST
import esprima
from esprima.visitor import Visited,Visitor
from esprima.nodes import *
import etc.__escodegen as escodegen
from mi.mi_gui import Ctx_gui
import json
from mi.mi_monkey import Ctx_monkey,MONKEYSCRIPT




class Ctx_forcejs(Ctx_base):

    @classmethod
    def is_webpack(cls,flow:HTTPFlow):
        return flow.request.url.endswith(".js") and not "vendor" in flow.request.url and flow.response.status_code==200 # 跳过lib

    def __init__(self):
        super().__init__([RR.RESPONSE])

    def response(self, flow):
        if not super().response(flow):
            return
        if re.search(r"(app|main|index)\.[a-zA-Z0-9]{1,}\.js", flow.request.url):
            # 随便写写
            rss = re.findall(
                "[\"'](chunk-[a-zA-Z0-9]{1,})[\"']\:\s?[\"']([a-zA-Z0-9]{1,})[\"']",
                Ctx_base.autocode(flow.response, flow.response.raw_content),
            )
            res = flow.response.text
            for c, k in rss:
                jsurl = "{0}/{1}.{2}.js".format(
                    flow.request.url.rsplit("/", 1)[0], c, k
                )
                if requests.head(jsurl).status_code != 200:
                    continue  # 跳过不是js文件的部分
                res += "document.head.appendChild(document.createElement('script')).src ='{0}';".format(
                    jsurl
                )
            flow.response.text = res


# 根据js响应提取API
class Ctx_url(Ctx_base):

    def __init__(self):
        super().__init__([RR.RESPONSE])

# 路由强制注册 一想到哪一天我被整破防了换js这些都要重写我就想321
# 这应该是最长的函数

class Ctx_router(Ctx_chainboot):

    vue={}

    def __init__(self):
        super().__init__([RR.REQUEST,RR.RESPONSE], [
            Ctx_monkey([["proxy-router.js",MONKEYSCRIPT.OUTSIDE]]), # 注入router
            Ctx_forcejs(), # 强制加载js
            Ctx_proxypack(), # 暴露变量
            ]) 

    class __ast(AST):

        class ___ast(Visitor): # 你py连匿名类都不好写 esprima python到底为什么会这样写啊 这见鬼了
            def visit_CallExpression(self,node): 
                if isinstance(node.callee,StaticMemberExpression) and node.callee.property.name=="bind":
                    # 用了加载器 这里找一下webpack_require
                    node.callee.object.name="__mss_webpack_require__"
                if isinstance(node.callee,StaticMemberExpression) and node.callee.property.name!="bind" and node.callee.object.name=="__mss_webpack_require__" :
                    Ctx_router.vue[self.key]["loader"]=node.callee.property.name # 累死个人
                result = yield Visited(node.__dict__)
                yield result  # 不支持写一起 也很幽默

        def __init__(self, js,key):
            self.key=key
            super().__init__(js)  

        def visit_ObjectExpression(self,node):

        def visit_ArrayExpression(self,node):
            if(len(node.elements)>0): 
                for i in node.elements:
                    if not isinstance(i,ObjectExpression):
                        return
                    ispath=False
                    iscomponent=False # 有时候不知道我在写什么
                    if "path" in i.properties and ("component" in i.properties or "components" in i.properties):
                        if not "loader" in Ctx_router.vue[self.key]:
                            # 没有loader 读取一个
                            ___=Ctx_router.__ast.___ast()
                            ___.visit(_.key.value)
                            _.key.value=___.visit(_.key.value) # 就这样折磨所有人~
                    for _ in i.properties:
                        if _.key.name=="path":
                            ispath=True
                        if "component" in _.key.name:
                            iscomponent=True
                            if not "loader" in Ctx_router.vue[self.key]:
                                # 没有loader 读取一个
                                ___=Ctx_router.__ast.___ast()
                                ___.visit(_.key.value)
                                _.key.value=___.visit(_.key.value) # 就这样折磨所有人~
                    if not (ispath and iscomponent):
                        return
            # 检查每个成员的类型 成员的构成 符合就保存
                Ctx_router.vue[self.key]["router"].append(escodegen.generate(node))
            result = yield Visited(node.__dict__)
            yield result  # 不支持写一起 也很幽默

    def request(self, flow):
        if not super().request(flow):
            return
        if flow.request.path.endswith("/:ctx_routers"):
            print(Ctx_router.vue.get(flow.request.host, []))
            flow.response = http.Response.make(
                200,
                json.dumps(Ctx_router.vue.get(flow.request.host, [])).encode("utf-8"),
                {"Content-Type": "application/json"}
            )
        return True

            
    def response(self, flow):
        if not super().response(flow): return
        if not Ctx_forcejs.is_webpack(flow): return
        if not flow.request.host in Ctx_router.vue.keys():Ctx_router.vue[flow.request.host]={"router":[]} # 初始化
        content = Ctx_base.autocode(flow.response, flow.response.raw_content)
        print(flow.request.url)
        Ctx_router.__ast(content,flow.request.host) # 这里只查看不修改
        return True


    

# proxy app下变量和函数到window下

class Ctx_proxypack(Ctx_base):

    def __init__(self):
        super().__init__([RR.RESPONSE])

    class __ast(AST):

        def __init__(self, js): # _apphex 
            with open("monkey/proxy-var.js","r",encoding="utf8") as f:
                self.proxyjsvar=f.read()
            self.js=js
            self.code=esprima.parseScript(self.js)
            self.jsafter=escodegen.generate(self.traverse())

        def traverse(self):
            # 芝能自己来惹
            newnodes=[]
            newnodes.append(esprima.parseScript(f"window.__mss__={{}}")) #先初始化 你语言还有这事呢？
            if(len(self.code.body)==1): # 修正一下use strict的情况
                for node in self.code.body[0].expression.callee.body.body: # 谁能念出来 
                    #遍历所有语句，对子一级节点的VariableDeclaration 和 FunctionDeclaration上proxy
                    if isinstance(node,VariableDeclaration):
                        for i in node.declarations: #这里偷点懒 应该没事 有事再改
                            # 调的我也是快升天了
                            newnodes.append(esprima.parseScript(self.proxyjsvar.format(i.id.name,escodegen.generate(i.init))).body[0])
                            newnodes.append(esprima.parseScript(f"{i.id.name}={escodegen.generate(i.init)};"))
                    elif isinstance(node,FunctionDeclaration):
                        if len(node.params)<2: # 拦截1 和0参数的函数 # 过滤条件不必要
                            newnodes.append(node)
                            newnodes.append(esprima.parseScript(f"window.__mss__.{node.id.name}={node.id.name};"))
                        else:
                            newnodes.append(node)
                    elif isinstance(node,ExpressionStatement):
                        # 拦截 表达式，这里主要是拦截一下router
                        ## vue2 routes: vue3 history:  写累了之后写吧 
                        newnodes.append(node)
                    else:
                        newnodes.append(node)
                self.code.body[0].expression.callee.body.body=newnodes
            return self.code
        
    def response(self, flow):
        if not super().response(flow):
            return
        content = Ctx_base.autocode(flow.response, flow.response.raw_content)
        if flow.request.url.endswith(".js") and "app" in flow.request.url: # 先这么写  后面改
            flow.response.set_content(
                Ctx_proxypack.__ast(content).jsafter.encode("utf8")
            )


# 去除guard

class Ctx_antiguard(Ctx_base):

    class __ast(AST):

        def __init__(self,js:str,anti:list):
            self.anti=anti
            super().__init__(js)

        def visit_CallExpression(self, node):  # 死插件缩进我看着难受不缩进我也难受
            if isinstance(node.callee, StaticMemberExpression) and len(node.arguments) > 0 and isinstance(node.arguments[0], ArrowFunctionExpression) and len(node.arguments[0].params) == 3:
                if node.callee.property.name in ["beforeEach", "afterEach", "beforeResolve"]:
                    Ctx_gui.logger(f"清除hook，类型{node.callee.property.name}")
                    if self.anti == []:
                        node.arguments[0].body.body = [esprima.parseScript(
                            "console.log('已清除guard！')"), esprima.parseScript(f"{node.arguments[0].params[2].name}()")]
                    else:
                        nstr = escodegen.generate(node)
                        # 由于你py没有traverse 我不想做算法题，这里用原始方法 但是又由于esprima也是基于re的，相当于没降级 谢谢哦^ ^
                        for i in self.anti+["false"]:
                            node = esprima.parseScript(re.sub(
                                f'{node.arguments[0].params[2].name}\(.*?{i}.*?\)', f'{node.arguments[0].params[2].name}()', nstr))
            result = yield Visited(node.__dict__)
            yield result  # 不支持写一起 也很幽默

        def visit_Property(self, node):  # 谁想得到是这个函数 离谱
            if (isinstance(node.value, FunctionExpression) and len(node.value.params) == 3):
                # 这个写法好省电 感动了
                if node.key.name in ["beforeEnter", "beforeRouteEnter", "beforeRouteUpdate", "beforeRouteLeave"]:
                    Ctx_gui.logger(f"清除hook，类型{node.key.name}")
                    if self.anti == []:
                        node.value.body.body = [esprima.parseScript(
                            "console.log('已清除guard！')"), esprima.parseScript(f"{node.value.params[2].name}()")]
                    else:
                        nstr = escodegen.generate(node)
                        # 由于你py没有traverse 我不想做算法题，这里用原始方法 但是又由于esprima也是基于re的，相当于没降级 谢谢哦^ ^
                        for i in self.anti+["false"]: #默认会去掉false 有意见可以提issue
                            node = esprima.parseScript(re.sub(
                                f'{node.value.params[2].name}\(.*?{i}.*?\)', f'{node.value.params[2].name}()', nstr))
            result = yield Visited(node.__dict__)
            yield result  # 不支持写一起 也很幽默

    def __init__(self, antiroute=[]):
        super().__init__([RR.RESPONSE])
        self.anti = antiroute

    def response(self, flow):
        if not super().response(flow):
            return
        content = Ctx_base.autocode(flow.response, flow.response.raw_content)
        if flow.request.url.endswith(".js"):
            flow.response.set_content(
                Ctx_antiguard.__ast(content,self.anti).jsafter.encode("utf8")
            )


# 优化未开启作用域提升情况下的代码
class Ctx_packeaziler(Ctx_base):

    class __ast(AST):

        def visit_FunctionExpression(
            self, node
        ):  # 遍历方式充满了一种幽默感，评价是不如traverse
            if (node.id is None) and (len(node.params) == 3):
                for i in range(len(node.body.body)):
                    if (
                        isinstance(
                            node.body.body[i].expression, CallExpression)
                        and isinstance(node.body.body[i].expression.callee, Identifier)
                        and node.body.body[i].expression.callee.name == "eval"
                    ):
                        node.body.body[i] = esprima.parseScript(
                            node.body.body[i].expression.arguments[0].value
                        )
            result = yield node.__dict__
            yield Visited(result)

    def __init__(self):
        super().__init__([RR.RESPONSE])

    def response(self, flow):
        # 其实应该用re写 考虑到后续的扩展性还是使用ast
        if not super().response(flow):
            return
        content = Ctx_base.autocode(flow.response, flow.response.raw_content)
        # 这种特征其实还不是很明晰 先就这么写 有问题直接私聊我 这缩进真sb
        if flow.request.url.endswith(".js"):
            if (
                len(re.findall(r"[\/][\*]{2,}[\/]", content)) > 5
                and "/*! exports provided: default */" in content
            ):
                flow.response.set_content(
                    Ctx_packeaziler.__ast(content).jsafter.encode("utf8")
                )
