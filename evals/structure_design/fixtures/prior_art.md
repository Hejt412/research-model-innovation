# 合成提案与方法摘录

资料只供检验机制比较，不是真实论文、DOI 或联网查新。

项目提案“Support-Keyed Bi-Stream Modulator”实际计算：
a=relu(left(x)), b=relu(right(y))；
r_b=sigmoid(G(b)), r_a=sigmoid(G(a))；
a'=a+alpha*(r_b*a), b'=b+alpha*(r_a*b)；
logits=head(concat(a',b'))。
G 为共享 Linear(32,32,bias=True)，alpha 为预先固定的标量，alpha=0 是禁用路径。r 为逐特征门控；没有 support 输入，条件只来自另一路当前表示，query 标签不可用。不改变 loss/训练/数据协议。

合成同领域方法 F-old，题名“Reliability Transfer Across Views”（名称与项目提案不同），应用同样是两路逐样本分类，标签假设/协议相同。方法摘录：
u=relu(Ax), v=relu(By)；
t_v=sigmoid(Wv+c), t_u=sigmoid(Wu+c)；
u_plus=u+lambda*t_v*u, v_plus=v+lambda*t_u*v；
o=C[u_plus;v_plus]+d。
同一 W/c 在两路共享，lambda 固定；关闭 lambda 恢复原分类器。

另一合成方法 F-other 使用训练组身份给 loss 加权，没有模型内交互。两份摘录都可完整比较数学操作；访问现实原论文的状态仍是未执行。
