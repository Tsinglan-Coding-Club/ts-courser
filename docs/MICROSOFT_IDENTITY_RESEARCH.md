# Microsoft Entra ID 学校账号登录调研

> **范围**：为 Django 服务端渲染的校内学习平台评估 Microsoft Entra ID 登录；详细实施规划另见 [账号升级方案](ACCOUNT_SYSTEM_UPGRADE_PLAN.md)。
>
> **资料核验日期**：2026-09-03。除特别标注外，链接均为 Microsoft Learn 官方文档。
>
> **术语**：本文的「Entra 租户」指 Microsoft Entra workforce tenant；不是 Microsoft Entra External ID customer tenant。

## 用户已确认的业务事实（非 Microsoft 文档验证）

- 全体教师和学生（包括低年级学生）都有学校 Microsoft account；现有 Django accounts 仅为测试数据，**不做账号迁移**。
- 本地学生帐号是为了日常使用方便，不是缺少 Microsoft account 的替代方案。管理员将通过产品 UI 手动输入、粘贴或导入本地 admission/学生资料；用户不会提供预先整理的学生 roster。
- 学生地址约定为 `Firstname_Lastname_Graduationyear@schoolSuffix`；教师地址没有 graduation year。学校使用 Teams/Outlook，但目前不知道 Entra tenant ID 和 global/China cloud。

## 已核实的事实

### 账号边界：单租户并不等于只限本校成员

- App registration 的 **Accounts in this organizational directory only** 是 single-tenant；只有其 home tenant 的用户可登录。微软明确建议内部组织的目标受众选择它。 [Single and multitenant apps](https://learn.microsoft.com/en-us/entra/identity-platform/single-and-multi-tenant-apps)
- 但同一页面也明确写明：single-tenant 可使用该目录中的 **all user and guest accounts**。所以它会排除 personal Microsoft account 和其他租户的直接成员，却**不会自动排除已被邀请进本校租户的 B2B guest**。是否允许 guest 是租户与应用授权策略的另一层决定，不能仅凭 Supported account types 推断。 [同上](https://learn.microsoft.com/en-us/entra/identity-platform/single-and-multi-tenant-apps)
- **Accounts in any Microsoft Entra directory** 允许任何组织目录的用户和 guest；再加 personal Microsoft accounts 的选项则包含 Outlook.com、Xbox、Skype 等 MSA。因此均不符合「只准本校目录身份」这个较窄的目标。 [同上](https://learn.microsoft.com/en-us/entra/identity-platform/single-and-multi-tenant-apps)

**设计含义**：以本校 tenant GUID 作为固定 authority 的 single-tenant registration 是合理的起点；回调端还应把已验证 token 的 `tid` 与已配置 tenant GUID 比较。已确定排除 B2B guest：App registration 要 opt-in `acct` 并拒绝 `acct==1`，再以 app-role/local admission 落实；绝不能以邮箱后缀判断 guest 或授权。

### Azure global 与中国世纪互联云不可混用

- 各 national cloud 是彼此独立的 cloud instance，有独立环境、端点，并且应用必须在各自 Azure portal **分别注册**。 [National clouds](https://learn.microsoft.com/en-us/entra/identity-platform/authentication-national-cloud)
- Global 的认证基址为 `https://login.microsoftonline.com`；中国区 Microsoft Entra（由 21Vianet 运营）为 `https://login.partner.microsoftonline.cn`。single-tenant 请求应以 tenant ID 或 tenant name 替换路径中的 `common`。 [National clouds](https://learn.microsoft.com/en-us/entra/identity-platform/authentication-national-cloud)
- national cloud 的可用服务/功能可能与 global 不同；如果以后调用 Microsoft Graph，还必须选用对应 national cloud 的 Graph endpoint 与能力矩阵。 [National clouds](https://learn.microsoft.com/en-us/entra/identity-platform/authentication-national-cloud)

**设计含义**：配置不能只保存 `TENANT_ID`；还须明确 `CLOUD`/authority host，且将 client ID、credential、redirect URI 视为某一云环境内的资料。不要把 global App registration 的 ID/secret 直接拿到世纪互联端点使用，反之亦然。

**Teams/Outlook 能说明什么、不能说明什么**：Microsoft 文档说明 Microsoft Entra ID 是 Microsoft 365/Office 365 的目录服务，Teams 以 Entra ID 为身份后端；Teams 的 cloud-only 和 hybrid identity 都将组织帐号储存在 Entra ID。 [Teams security guide](https://learn.microsoft.com/en-us/microsoftteams/teams-security-guide)；[Teams identity models](https://learn.microsoft.com/en-us/microsoftteams/identify-models-authentication) 。所以「学校 Teams/Outlook 帐号」是学校很可能有可用 workforce tenant 的强信号，但**不能**提供 tenant GUID、不能证明学校允许新 App registration，也不能区分 global 与 21Vianet China。Teams public client 是 `teams.microsoft.com`，China 是 `teams.microsoftonline.cn`；而各云须独立注册应用。 [Teams sovereign clouds](https://learn.microsoft.com/en-us/microsoftteams/platform/concepts/sovereign-cloud)；[National clouds](https://learn.microsoft.com/en-us/entra/identity-platform/authentication-national-cloud) 。应由学校 IT 在 Entra/Microsoft 365 admin portal 确认 cloud、tenant GUID 和 app-registration 权限；不要据 Outlook/Teams 登录体验猜测。

### 登录协议与 MSAL Python 的责任

- Microsoft 对标准 server-based web application 支持 **OAuth 2.0 authorization code flow + OIDC**；同时建议所有 client（包括 confidential client）使用 **PKCE**，其中 `S256` 是应使用的方法。 [Authorization code flow](https://learn.microsoft.com/en-us/entra/identity-platform/v2-oauth2-auth-code-flow)
- 服务端 web app 能安全保存 client credential，属于 confidential client；MSAL Python 将 web apps/web APIs/daemon apps 归为此类，并提供 `ConfidentialClientApplication`。 [MSAL Python overview](https://learn.microsoft.com/en-us/entra/msal/python/)
- 必须将回调 `redirect_uri` 预先登记，且 authorization request 中的值必须与登记值**精确匹配**；code flow 需 `response_type=code`。 [Authorization code flow](https://learn.microsoft.com/en-us/entra/identity-platform/v2-oauth2-auth-code-flow)
- Microsoft 将 ID token 用于 client 对用户的 authentication。对于 confidential client，官方 ID-token 文档要求验证签名之后再验证时间（`iat`/`nbf`/`exp`）、`aud` 等于本 app ID、以及 `nonce` 等于初始 authorize request 的值；通用 token 文档也规定 application 负责验证 token。 [ID tokens](https://learn.microsoft.com/en-us/entra/identity-platform/id-tokens)；[Tokens and claims overview](https://learn.microsoft.com/en-us/entra/identity-platform/security-tokens)

**设计含义**：Django 仍须维护自己的短期、受保护 session；在发起登录时保存并在回调验证 `state`（CSRF）与 `nonce`，用 MSAL 交换 code 后才建立本地 session。PKCE 不取代 confidential-client 的 credential：两者可并用。由于 Pyodide 的 COOP/COEP 同源隔离要求，此流程应采用浏览器的**顶层页面 redirect**，而非 popup 或 iframe（这是本仓库的部署设计约束，非 Microsoft 文档结论）。

**MSAL Python 的精确边界（固定版本）**：本次固定核验官方发布版本 **1.38.0**，发布提交为 `b5bf1539ffa5afb39d0e4559b528468d66fb3a55`。项目当前 `pyproject` 尚未声明 MSAL，故这只是研究所固定的行为版本，**不是已安装的依赖版本**。 [1.38.0 release](https://github.com/AzureAD/microsoft-authentication-library-for-python/releases/tag/1.38.0)；[固定提交的 `oidc.py`](https://github.com/AzureAD/microsoft-authentication-library-for-python/blob/b5bf1539ffa5afb39d0e4559b528468d66fb3a55/msal/oauth2cli/oidc.py)

- 1.38.0 的 token acquisition **不验证 ID token**；`id_token_claims` 只是未验证的解码 claims；`decode_id_token()` 已在该版本 deprecated。它不会为 Django 自动检查 signature、issuer、`aud`、`exp`/`nbf`/`iat` 或 `tid`。 [固定源码](https://github.com/AzureAD/microsoft-authentication-library-for-python/blob/b5bf1539ffa5afb39d0e4559b528468d66fb3a55/msal/oauth2cli/oidc.py)
- 使用 `initiate_auth_code_flow()` / `acquire_token_by_auth_code_flow()` 的当前 flow 会生成和校验 nonce（token 中 nonce 为该随机 nonce 的 hash），并实现 PKCE；只有调用方传入 `max_age` 时，还会检查 `auth_time` 是否存在和是否超时。该 flow 未补上 signature/issuer/audience/lifetime/tenant 检查。 [固定源码](https://github.com/AzureAD/microsoft-authentication-library-for-python/blob/b5bf1539ffa5afb39d0e4559b528468d66fb3a55/msal/oauth2cli/oidc.py)
- 该源码引用 OIDC 规则说明：code 由 client 直接经 TLS 从 token endpoint 得到 ID token 时，TLS server validation **可以**替代 issuer signature check；这不是对所有 claims 的验证，也不能适用于浏览器转交 token 的设计。 [固定源码](https://github.com/AzureAD/microsoft-authentication-library-for-python/blob/b5bf1539ffa5afb39d0e4559b528468d66fb3a55/msal/oauth2cli/oidc.py)

**结论**：回调只接受服务器以 HTTPS 向固定 tenant token endpoint 交换 code 的结果，绝不接受浏览器提交的 ID token。安全基线应由应用验证 `state`、MSAL nonce、固定 `tid`，并仅按经允许的 app role/local admission 建会话；最符合 Microsoft 通用 confidential-client 指引的严格选择是额外用 discovery/JWKS JWT 验证器核验 signature、issuer、audience、lifetime、nonce 与 `tid`。若学校选择上述 OIDC 的 direct-TLS 例外而不验 signature，须把它记录为明确的安全设计决定；无论哪种路径都不得把 `id_token_claims` 本身当作已验证的授权结论。

### 登录所需 scopes 与 Graph

- `openid` 是 OIDC sign-in 的必需 scope，可获取 ID token；`profile` 可提供姓名、`preferred_username` 和 object ID 等；`email` 只在账号有邮件地址时才可能提供 `email` claim。 [OIDC scopes](https://learn.microsoft.com/en-us/entra/identity-platform/scopes-oidc)
- `offline_access` 是获取 refresh token 的 scope；v2.0 endpoint 必须显式请求它。它用于长期代表用户访问资源，不是建立本地网页登录 session 的必要条件。 [OIDC scopes](https://learn.microsoft.com/en-us/entra/identity-platform/scopes-oidc)
- `User.Read` 是 Microsoft Graph delegated permission（未带 resource identifier 的 `User.Read` 等价于 Graph 的权限），返回的 access token 只能用于 Graph；它不是接收 ID token 的前置条件。 [OIDC scopes](https://learn.microsoft.com/en-us/entra/identity-platform/scopes-oidc)

**MSAL Python 的 scope 细节（固定 1.38.0）**：`ClientApplication` 会把 `openid`、`profile`、`offline_access` 作为 reserved scopes 自动加到 wire request；调用方把其中任何一个放进传给 MSAL 的输入 `scopes` 会触发 `ValueError`。默认会因而请求 `offline_access`；要实现本项目的无 refresh-token 登录，初始化 client 时须使用 `exclude_scopes=["offline_access"]`。`openid` 不可排除，且输入 scopes 不应显式传 `openid`/`profile`/`offline_access`。 [MSAL 1.38.0 `application.py`](https://github.com/AzureAD/microsoft-authentication-library-for-python/blob/b5bf1539ffa5afb39d0e4559b528468d66fb3a55/msal/application.py)；[MSAL API reference](https://learn.microsoft.com/en-us/python/api/msal/msal.application.confidentialclientapplication?view=msal-py-latest)

**设计含义**：协议层最小身份 scope 是 `openid profile`，但 MSAL 1.38.0 的正确调用形态是输入不含 reserved scope（无 Graph 需求时可为空）并排除 `offline_access`。如果只显示但不依赖 email，不请求 `email`。不调用 Graph 时，不申请 `User.Read`，也不应保存 Graph access token。

### 地址格式只可作首登分类提示

- `preferred_username` 可以是 email、电话号码或任意 username；它可变、没有指定格式，Microsoft 明确规定不得用于 authorization decision，只适合显示和 username hint。`profile` scope 才会带该 claim。 [ID token claims reference](https://learn.microsoft.com/en-us/entra/identity-platform/id-token-claims-reference)
- `email` 对 managed user 需 `email` scope 或 optional claim 才可请求，且不保证正确、可变；不得把它作为 authorization 或用户数据归属的标识键。有些帐号没有该 claim；需要联系地址时可将其作为界面预填建议，再由用户确认。 [ID token claims reference](https://learn.microsoft.com/en-us/entra/identity-platform/id-token-claims-reference)
- UPN 是用户的 sign-in address，primary SMTP/mailbox address 是 Exchange recipient 的主邮件地址；一个 mailbox 可以有多个 proxy/alias 邮件地址。Entra 还可配置让用户用 `ProxyAddresses` 的 email 而不是 UPN 登录。因此「用户在 Teams/Outlook 使用的邮箱」「token 的 `preferred_username`」「UPN」可能相同，也可能不同。 [UPN, primary SMTP and mail definitions](https://learn.microsoft.com/en-us/troubleshoot/entra/entra-id/user-prov-sync/proxyaddresses-attribute-populate)；[Email as alternate login ID](https://learn.microsoft.com/en-us/entra/identity/authentication/howto-authentication-use-email-signin)；[Email aliases](https://learn.microsoft.com/en-us/microsoft-365/admin/email/add-another-email-alias-for-a-user)
- Microsoft 推荐跨应用且同 tenant 关联用户时用 immutable `oid` 和 `tid`；email、UPN 会随改名/复用而变化。 [ID token claims reference](https://learn.microsoft.com/en-us/entra/identity-platform/id-token-claims-reference)

**本项目建议**：只在已验证的固定 `tid`、非 guest（`acct==0`）首登之后，才可对可获得的 `preferred_username` 或 `email`（若存在）尝试匹配 `Firstname_Lastname_Graduationyear@schoolSuffix`。匹配到年份只能给出「Student 候选」分类提示，可预填本地学生资料或进入学生待准入状态；不匹配、缺少 claim、别名、UPN 与邮箱不一致及地址改名都应交由所选准入策略处理，不能否定已验证的既有身份。**没有 graduation year 绝不自动授予 Teacher、staff 或任何管理权限。**地址解析不需要、也不应为此新增 Microsoft Graph permission；最终身份键始终是 `(tid, oid)`，具体准入策略见主方案，不由地址格式作出。

### 用户主键、角色和学校授权

- `oid` 是用户/服务主体的 immutable identifier；同一用户在同一 tenant 被不同 app 登录时 `oid` 相同；用户在不同 tenant 有不同 object ID。`tid` 是 tenant 的 immutable GUID，应与其他 claim 一起参与 authorization decision。 [Access token claims reference](https://learn.microsoft.com/en-us/entra/identity-platform/access-token-claims-reference)
- `email` claim 不保证存在；`preferred_username`/UPN 适合展示或辅助匹配，均不应是长期外部身份主键。 [OIDC scopes](https://learn.microsoft.com/en-us/entra/identity-platform/scopes-oidc)
- App roles 在 application registration 上声明；用户或组被授予角色时，Entra 在 token 中发出 `roles` claim。App roles 与 groups 不同：前者随 app 存在、后者是 tenant 的独立对象。 [App roles](https://learn.microsoft.com/en-us/entra/identity-platform/howto-add-app-roles-in-apps)
- Enterprise application 的 **Assignment required = Yes** 后，只有直接分配或通过组分配的用户能登录；未启用时，未分配用户仍可通过应用发起登录。启用 assignment required 时，必须由管理员作 tenant-wide admin consent。 [Manage access to apps](https://learn.microsoft.com/en-us/entra/identity/enterprise-apps/what-is-access-management)
- 对 Enterprise app 做 group-based assignment 需要 Microsoft Entra ID P1 或 P2；直接 individual assignment 是另一种管理方式。 [Manage access to apps](https://learn.microsoft.com/en-us/entra/identity/enterprise-apps/what-is-access-management)
- Assignment required 的例外是 **Global Administrator**：其可在未分配时登录；没有 named app role 的 Default Access 虽满足 assignment requirement，却不会向 token 加 `roles` claim。嵌套 group membership 也不应作为可预测授权依据。 [AADSTS50105 troubleshooting](https://learn.microsoft.com/en-us/troubleshoot/entra/entra-id/app-integration/error-code-aadsts50105-user-not-assigned-role)
- `acct` 是可选 claim：member 为 `0`、guest 为 `1`。Microsoft 明确建议要阻挡 guest 时在 App registration opt-in `acct` 并拒绝 `acct==1`；因此不能仅以 assignment/role grant 防 guest。 [Optional claims reference](https://learn.microsoft.com/en-us/entra/identity-platform/optional-claims-reference)；[Customize Entra tokens](https://learn.microsoft.com/en-us/security/zero-trust/develop/zero-trust-token-customization)

**本项目建议（身份边界）**：外部身份键为 `(tid, oid)`，email/UPN 仅是可更新资料。Entra app-role 模式只接受 `Student`、`Teacher`；受信任 role 决定对应平台身份，角色允许列表也能挡住 Global Administrator 的 assignment-required 例外。App registration 应请求 ID-token optional claim `acct`，应用明确要求 `acct==0`，缺失或 guest 都拒绝。**绝不**读取或映射 Entra directory role/`wids`，也绝不把 SSO、Global Administrator 或任意 Entra 管理权限自动提升为平台 `is_staff`/`is_superuser`/站内管理员。

主方案另允许两个明确选择的本地策略：逐人准入模式下，新身份未获批准前仅能访问待审核状态；学校成员准入模式须由 IT 确认本校成员范围，符合策略的成员默认只有学习权限，教师权限另由管理员批准。前者需要逐人准入记录，后者是学校明确授权的成员范围，均不通过邮箱格式决定权限；不能在 Microsoft 角色配置出错时自动降级到另一模式。课程归属、评分和站内管理员仍由 Django 本地授权决定。

**需要学校作出的开关选择**：若 Enterprise application 设为 Assignment required，未获 direct/group assignment 的普通用户在到达平台 pending 页面前就被 Entra 拦截；要允许「所有已验证本校 member 首登后 pending」，要么不启用该 Entra 开关而由 Django 的 `acct`、角色/本地 admission 逐层拒绝敏感访问，要么给可首登用户 Default Access/direct assignment（它不会产生 `roles` claim）并仍由 Django 把无 `Student`/`Teacher` role 的人置为 pending。两种都不影响 guest 的 `acct==1` 拒绝；选择前者或后者是管理流程与许可的取舍，不能同时声称 assignment-required 会拦住未分配用户、又让他们首登 pending。 [AADSTS50105 troubleshooting](https://learn.microsoft.com/en-us/troubleshoot/entra/entra-id/app-integration/error-code-aadsts50105-user-not-assigned-role)

### 最小 App registration / 管理员输入

下列信息是完成 single-tenant confidential web-client 登录所需的最小配置资料；这些是配置输入，不是都应作为 secret：

| 项目 | 用途与保密性 |
| --- | --- |
| Tenant (Directory) ID | 固定 authority、验证 `tid`；标识符，非 secret。 |
| Application (client) ID | 在 authorize/token 识别 app、验证 `aud`；标识符，非 secret。 [Authorization code flow](https://learn.microsoft.com/en-us/entra/identity-platform/v2-oauth2-auth-code-flow) |
| Cloud / authority host | Global 或 China 端点选择；非 secret。 [National clouds](https://learn.microsoft.com/en-us/entra/identity-platform/authentication-national-cloud) |
| 精确的 Web redirect URI（生产和必要的本地开发各自登记） | Entra 回传 code；不是 secret，但属于严格 allowlist。 [Authorization code flow](https://learn.microsoft.com/en-us/entra/identity-platform/v2-oauth2-auth-code-flow) |
| client secret **或更优的 certificate** | confidential client 向 token endpoint 证明 app 身份；必须只放服务器机密存储/环境，不进仓库、不发浏览器。Microsoft 建议将 secret 放 Key Vault 或加密配置文件，避免明文及版本控制。 [Confidential clients](https://learn.microsoft.com/en-us/entra/identity-platform/msal-client-applications) |
| Supported account types = 本目录 | 约束为 single tenant；非 secret。 [Single and multitenant apps](https://learn.microsoft.com/en-us/entra/identity-platform/single-and-multi-tenant-apps) |

管理员还应确认是否设置 **Assignment required**、将哪些用户/组分配给 Enterprise application、是否定义 `Student`/`Teacher` app roles、以及由谁持有/轮换 credential。首登本地 admission 的输入、粘贴及导入由产品 UI 管理，不依赖既有帐号迁移或学校预交 roster。若只用 `openid profile`，不需新增 Graph API permission 或 Graph admin consent。

### 本地 session、登出与停用账号

- OIDC front-channel logout 可通知各已登录 app 清除各自 session，但每个 app 要设置 front-channel logout URL，并且收到 GET 时清 session、回 `200`；用户仍可能在使用同一 Microsoft account 的其他应用处于登录状态。 [OIDC logout](https://learn.microsoft.com/en-us/entra/identity-platform/v2-protocols-oidc)
- Entra 管理员阻止新登录、撤销 refresh token 后，既有 application session 并不会即时、自动地失效：对 session token 的失效时间取决于 session token 到期；若 disabled 状态同步到应用，才可按同步频率撤销。微软建议自动 provisioning/deprovisioning，典型周期为 20–40 分钟，并要求应用撤销自己的 session。 [Revoke user access](https://learn.microsoft.com/en-us/entra/identity/users/users-revoke-access)
- confidential-client refresh token 不会因普通 single sign-out 而一概失效；refresh token 也可能随时被撤销，应用需能重新引导 interactive sign-in。 [Refresh tokens](https://learn.microsoft.com/en-us/entra/identity-platform/refresh-tokens)

**设计含义**：应用内「退出」必须先删除 Django session；可再导向 Entra logout endpoint 以结束 IdP browser session，不能承诺能退出所有 Microsoft 应用。登录整合本身也不会把 Entra 的禁用/离校事件即时推送到本地 Django user；要满足离校即时禁用，需另行决定本地 session 最大寿命、每次/定期重新认证、人工停用流程或受支持的 provisioning/deprovisioning 集成。仅登录且不保存 refresh token 时，风险面较小，但本地 session 仍需主动治理。

## 本校尚待确认的决策

1. 学校实际使用 global Azure 还是由世纪互联运营的 China cloud？两者需要独立注册与配置。
2. 方案默认不包括 B2B guest；若校内人员实际以 guest 登记，需要 IT 核实。采用 app roles、逐人准入，还是经学校确认的成员准入＋教师审核？相应产品 UI 由谁维护？
3. 学校是否拥有/愿意使用 P1/P2 的 group-based app assignment，还是采用不需该许可的 direct individual assignment，并给用户直接分配 `Student`/`Teacher` role？
4. 产品 UI 的批量粘贴/导入最小字段、重复 `(tid, oid)`/地址候选的人工处理，以及 Student pending / Teacher pending 的审批人分别是谁？（无既有帐号迁移要求。）
5. 离校、停学、教师离职的可接受撤销时限是多少？是否需要 provisioning，还是由校务人员手工停用本地帐号？
6. 是否存在需要 Microsoft Graph 的明确功能（头像、班级/组同步、目录查询等）？在未定义该功能前，不要预先申请 `User.Read`、`Group.Read.*` 或 `offline_access`；地址模式分类也不是 Graph 的理由。

## 建议的决策顺序

1. 先由学校 IT 确认 cloud、tenant GUID、guest 政策和离校 SLA。
2. 注册 single-tenant **Web** application，限定精确 HTTPS redirect URI，并选定 secret/certificate 的保管与轮换责任人。
3. 按选择的准入模式配置 Assignment required 和 `acct`；app-role 模式分配 Student/Teacher，本地模式明确默认权限与审核流程。应用拒绝 guest 和 directory-admin 自动提升；不依据地址格式自动成为教师。
4. 以 MSAL 1.38.0 行为为准时，输入 scopes 留空并用 `exclude_scopes=["offline_access"]`，使 wire request 保持 `openid profile`；只有已批准、可说明用途的数据调用才追加 Graph permission 或长期访问。
