import os
import yaml
import json
import requests
import re
import time
import urllib3
from urllib.parse import urlparse

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


class APIExecutor:
    def __init__(self):
        self.base_dir = os.path.dirname(os.path.abspath(__file__))
        self.apis_dir = os.path.join(self.base_dir, "captured_apis")
        self._cached_base_url = None

    def list_yaml_files(self):
        if not os.path.exists(self.apis_dir):
            return []
        return [f for f in os.listdir(self.apis_dir) if f.endswith(".yaml")]

    def run(self):
        print("\n" + "═"*55)
        print("  🧪  API Executor  |  接口快速调测工具")
        print("═"*55)

        while True:
            # 1. 选择文件
            files = self.list_yaml_files()
            if not files:
                print("\n❌ captured_apis/ 目录下没有任何 YAML 文件")
                print("   请先运行 api_recorder.py 录制接口并导出。\n")
                return

            print(f"\n📂 发现 {len(files)} 个模块 (输入 q 退出):\n")
            for idx, f in enumerate(files, 1):
                print(f"  [{idx}] {f}")

            user_input = input("\n请选择模块编号: ").strip().lower()
            if user_input == 'q':
                print("\n👋 已退出。\n")
                break

            try:
                f_idx = int(user_input) - 1
                filename = files[f_idx]
            except (ValueError, IndexError):
                print("  ❌ 输入无效，请输入列表中的数字编号\n")
                continue

            # 2. 解析 YAML
            with open(os.path.join(self.apis_dir, filename), 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f)

            apis = config.get("apis", {})
            if not apis:
                print("  ❌ 该 YAML 文件中没有找到任何接口定义\n")
                continue

            # 设置 Base URL（模块级别，一次输入全局复用）
            if not self._cached_base_url:
                print("\n" + "─"*55)
                self._cached_base_url = input("  🌐 请输入 Base URL (如 https://api.example.com): ").strip().rstrip('/')
                print("─"*55)

            # 3. 接口菜单
            while True:
                api_keys = list(apis.keys())
                print(f"\n{'─'*55}")
                print(f"  📦 模块: {filename.replace('.yaml','')}   共 {len(api_keys)} 个接口")
                print(f"{'─'*55}")
                print("  [0]  ▶ 顺序执行全部")
                for idx, k in enumerate(api_keys, 1):
                    name = apis[k].get("name", "未命名")
                    method = apis[k].get("method", "GET")
                    path = apis[k].get("path", "")
                    print(f"  [{idx}]  {method:<6} {path}   ({name})")
                print(f"{'─'*55}")
                print("  [b] 返回模块列表  |  [u] 更换 Base URL  |  [q] 退出")

                choice = input("\n请选择操作: ").strip().lower()

                if choice == 'b':
                    break
                if choice == 'q':
                    print("\n👋 已退出。\n")
                    return
                if choice == 'u':
                    self._cached_base_url = input("  🌐 新 Base URL: ").strip().rstrip('/')
                    print(f"  ✅ Base URL 已更新: {self._cached_base_url}\n")
                    continue

                if choice == '0':
                    print(f"\n🚀 开始顺序执行 {len(api_keys)} 个接口...\n")
                    self._batch_mode = True
                    for i, k in enumerate(api_keys, 1):
                        print(f"  ── [{i}/{len(api_keys)}] ──────────────────────────")
                        self._execute_single_api(apis[k])
                    self._batch_mode = False
                    print(f"\n{'─'*55}")
                    print(f"  ✅ 全部执行完毕")
                    input("  按回车键继续...")
                else:
                    try:
                        k_idx = int(choice) - 1
                        if k_idx < 0:
                            raise ValueError
                        self._batch_mode = False
                        self._execute_single_api(apis[api_keys[k_idx]])
                        input("\n  按回车键继续...")
                    except (ValueError, IndexError):
                        print("  ❌ 输入无效\n")

    def _prompt_body(self, body, prefix=""):
        """交互式逐字段修改 body，回车跳过保持默认值，自动保持数据类型"""
        import copy
        result = copy.deepcopy(body)
        print(f"  \U0001f4dd 修改请求参数 (直接回车保留默认值):")
        for k, v in result.items():
            full_key = f"{prefix}{k}" if prefix else k
            if isinstance(v, dict):
                print(f"     {full_key}: {{…}}")
                result[k] = self._prompt_body(v, prefix=f"{full_key}.")
            else:
                raw = input(f"     {full_key} [{v}] = ").strip()
                if raw:
                    result[k] = self._cast(raw, v)
        return result

    def _cast(self, raw, original):
        """按照原始值类型尝试转换输入字符串"""
        if isinstance(original, bool):
            return raw.lower() in ('true', '1', 'yes', '是')
        if isinstance(original, int):
            try: return int(raw)
            except: return raw
        if isinstance(original, float):
            try: return float(raw)
            except: return raw
        return raw

    def _execute_single_api(self, api_info):
        path = api_info['path']
        method = api_info['method']
        headers = {k: v for k, v in api_info.get('headers', {}).items() if not k.startswith(':')}
        body = api_info.get('default_body', {})
        body_type = api_info.get('body_type', 'json')
        name = api_info.get('name', '未命名接口')

        print(f"\n  🔗 {name}")

        # 处理路径参数
        path_params = re.findall(r'\{(\w+)\}', path)
        if path_params:
            print(f"  📝 路径参数: {path_params}")
            for p in path_params:
                val = input(f"     {p} = ").strip()
                if val:
                    path = path.replace(f"{{{p}}}", val)

        # 拼接完整 URL
        if not path.startswith("http"):
            base = self._cached_base_url or ""
            url = f"{base}/{path.lstrip('/')}"
        else:
            url = path

        # 交互式修改 Body 字段（单接口模式下开放，批量执行直接跳过）
        if body and not getattr(self, '_batch_mode', False):
            body = self._prompt_body(body)

        print(f"  → {method} {url}")
        if body:
            print(f"  📤 Body: {json.dumps(body, ensure_ascii=False)}")



        # 使用最基础的 requests 库
        import requests
        
        # 清理冗余或可能导致冲突的 headers
        clean_headers = {k: v for k, v in headers.items() if not k.startswith(':')}
        
        # 自动同步 Origin 和 Referer 域名，防止被 WAF 的跨域规则拦截
        from urllib.parse import urlparse
        parsed_url = urlparse(url)
        target_origin = f"{parsed_url.scheme}://{parsed_url.netloc}"
        
        # 统一转为小写处理，并纠正域名
        new_headers = {}
        for k, v in clean_headers.items():
            k_low = k.lower()
            if k_low == 'origin':
                new_headers[k_low] = target_origin
            elif k_low == 'referer':
                ref_parsed = urlparse(v)
                if ref_parsed.netloc:
                    new_headers[k_low] = v.replace(f"{ref_parsed.scheme}://{ref_parsed.netloc}", target_origin)
                else:
                    new_headers[k_low] = v
            elif k_low.startswith('sec-'):
                continue # 跳过敏感的浏览器指纹头部
            else:
                new_headers[k_low] = v
        
        clean_headers = new_headers

        try:
            start_time = time.time()
            if method.upper() == 'GET' or body_type == 'params':
                response = requests.request(method, url, headers=clean_headers, params=body, timeout=15, verify=False)
            elif body_type == 'json':
                response = requests.request(method, url, headers=clean_headers, json=body, timeout=15, verify=False)
            else:
                response = requests.request(method, url, headers=clean_headers, data=body, timeout=15, verify=False)

            elapsed = (time.time() - start_time) * 1000
            status = response.status_code
            status_icon = "✅" if 200 <= status < 300 else "❌"
            print(f"  {status_icon} 状态码: {status}  |  耗时: {elapsed:.0f}ms")

            # 断言检查
            assertions = api_info.get("assertions", [])
            for a in assertions:
                a_type = a.get("type")
                expected = a.get("expected")
                if a_type == "status_code":
                    ok = response.status_code == expected
                    icon = "✅" if ok else "❌"
                    print(f"  {icon} 断言 status_code: 期望 {expected}, 实际 {response.status_code}")
                elif a_type == "json_path":
                    path_expr = a.get("path")
                    try:
                        res_json = response.json()
                        actual = res_json
                        for key in path_expr.split('.'):
                            actual = actual.get(key) if isinstance(actual, dict) else None
                        ok = actual == expected
                        icon = "✅" if ok else "❌"
                        print(f"  {icon} 断言 json_path [{path_expr}]: 期望 {expected}, 实际 {actual}")
                    except:
                        print(f"  ⚠️ 断言 json_path [{path_expr}] 执行失败")

            # 单接口模式展示响应摘要
            if not getattr(self, '_batch_mode', False):
                try:
                    res_json = response.json()
                    preview = json.dumps(res_json, indent=2, ensure_ascii=False)
                    lines = preview.splitlines()
                    if len(lines) > 12:
                        preview = "\n".join(lines[:12]) + f"\n  ... (共 {len(lines)} 行)"
                    print(f"\n  响应预览:\n{preview}")
                except:
                    text = response.text[:300]
                    print(f"\n  响应文本: {text}")

        except Exception as e:
            print(f"  ❌ 请求失败: {e}")


if __name__ == "__main__":
    executor = APIExecutor()
    try:
        executor.run()
    except KeyboardInterrupt:
        print("\n\n👋 已中断退出。\n")
