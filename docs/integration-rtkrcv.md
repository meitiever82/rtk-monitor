# rtkrcv 真机集成核对清单

上车/联调时逐项核对（单元测试覆盖不到的部分）：

- [ ] `scripts/build_rtkrcv.sh` 在目标机（ARM64）构建通过；`tools/bin/rtkrcv -h` 可运行
- [ ] config.yaml `rtkrcv.binary` 指向该二进制；启动后 `ps` 可见进程、事件表出现 rtkrcv connected
- [ ] 核对 conf 键名与 demo5 版本一致（`rtkrcv.conf` 由程序生成在 `<data_root>/rtkrcv/`）：
      inpstr1/2、outstr1、pos1-posmode、pos2-armode——不一致则改 `solver/rtkrcv.py` 模板
- [ ] `-nc` 参数在该版本可用（禁用控制台）；不可用则从命令行移除并验证后台运行
- [ ] 板卡原始观测格式确认：`convbin -scan` 判别 RTCM3 还是华测二进制；
      非 RTCM3 时改 conf `inpstr1-format`
- [ ] solution 流通：`nc 127.0.0.1 <sol_port>` 能看到 llh 行；epochs 表出现 src='rtkrcv'
- [ ] solution status（规则 4/6 的输入）：确认 demo5 rtkrcv 输出 $SAT 的配置方式
      （outstat 相关键），接通后把 stat 流喂给 `parse_sat_line`/`SlipWindow`——
      当前 App 的 `sats`/slip 输入为空，规则 4/6 不触发，属预期降级
- [ ] 固定率合理性：开阔地静止 5 分钟，Q=1 占比 > 90%
- [ ] 基站坐标来源核对：conf 已加 `ant2-postype =rtcm`（从 RTCM 1005/1006 取基站坐标）；
      rtkrcv console status 中确认基站坐标确实来自 RTCM（而非本地静态配置）
- [ ] 48 小时 soak 后核对数据库体积：rtkrcv epoch 写入已按 1Hz 抽稀（与 gpchc/can 一致）；
      长期留存策略见 Plan 3
