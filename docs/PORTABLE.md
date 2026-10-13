# 다른 PC에서 사용하기

이 패키지는 소유자가 자신의 Windows PC 사이에서 옮겨 사용하는 포터블 프로그램입니다. 설치 프로그램이 없으며 Python·모델을 별도로 설치하지 않습니다. Windows 11 x64와 CPU 처리를 기준으로 검증했습니다. ARM Windows 및 다른 Windows 버전은 검증하지 않았습니다.

## 옮길 파일과 실행

1. `dist/MeetingTranscriber-v0.1.3-win-x64.zip`과 함께 있는 `.zip.sha256` 파일을 다른 PC로 복사합니다. USB·개인 저장 공간 등으로 전달하면 됩니다.
2. ZIP을 **폴더 전체로 압축 해제**합니다. ZIP 내부에서 EXE를 바로 실행하지 않습니다.
3. 압축 해제된 `MeetingTranscriber/MeetingTranscriber.exe`를 실행합니다.
4. 해당 PC의 마이크·PC 출력 장치를 선택하고 기록을 시작합니다. 장치 이름은 PC마다 다릅니다.

`_internal`, `models`, `licenses`, `docs`와 함께 있는 파일들을 유지하세요. EXE만 옮기면 실행되지 않습니다. GitHub에서 전달하려면 이 ZIP을 Release 첨부 파일로 사용합니다. 개인 용도로 사용한다는 이유만으로 공개 저장소의 Release가 비공개가 되는 것은 아닙니다. v0.1.3부터 비공개 저장소의 Release에 ZIP과 체크섬을 첨부합니다.

다운로드와 파일 이동이 끝나면 실행에 인터넷 연결은 필요 없습니다. 온라인 회의 프로그램의 네트워크 사용은 별개입니다. 앱은 외부 인식 서비스로 자동 대체하거나 실행 중 모델을 내려받지 않습니다.

## 파일 검증과 새 PC 진단

압축 파일과 체크섬을 같은 폴더에 둔 상태에서 PowerShell로 확인할 수 있습니다.

```powershell
$zip = '.\MeetingTranscriber-v0.1.3-win-x64.zip'
$expected = ((Get-Content -LiteralPath "$zip.sha256").Trim() -split '\s+')[0]
(Get-FileHash -LiteralPath $zip -Algorithm SHA256).Hash -eq $expected
```

`True`이면 체크섬과 일치합니다. 체크섬은 다운로드·복사 중 손상을 확인하는 용도이며 게시자 서명은 아닙니다.

압축 해제한 `MeetingTranscriber` 폴더에서 다음 명령은 모든 패키지 파일의 SHA-256을 검사합니다.

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\check_package.ps1
```

다음 명령은 파일 검사 후 로컬 모델·AEC·숨긴 예시 UI·한국어 PDF 생성까지 확인합니다. 실제 마이크를 녹음하지 않으며 회의 음성을 수집하지 않습니다. 오디오 장치 목록은 확인합니다.

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\check_package.ps1 -CheckRuntime
```

이 명령의 `ExecutionPolicy Bypass`는 해당 PowerShell 프로세스에만 적용합니다. 시스템 정책을 저장하거나 방화벽을 변경하지 않습니다. 진단 결과는 `%LOCALAPPDATA%\StandaloneMeetingTranscriber\checks`에 저장하며, 실행 상태 로그는 `logs`에 별도로 생성합니다.

진단에 통과해도 실제 마이크 권한·회의 음질·처리 속도는 새 PC에서 확인해야 합니다. 마이크 사용이 실패하면 Windows 설정 → 개인정보 및 보안 → 마이크에서 마이크 액세스와 데스크톱 앱 액세스를 확인합니다.

## 데이터와 업데이트

설정·회의록·로그는 기본적으로 `%LOCALAPPDATA%\StandaloneMeetingTranscriber`에 저장합니다. 배포 ZIP에는 이 개인 데이터가 포함되지 않습니다. 기존 PC의 회의록을 이어서 열려면 필요한 `session.json`을 따로 복사합니다. Markdown·PDF도 필요한 파일만 별도로 옮깁니다.

업데이트는 프로그램을 종료하고 새 ZIP을 **별도의 새 폴더**에 풉니다. 사용자 데이터는 위의 별도 위치에 남습니다. 이전 실행 파일 폴더를 삭제하기 전에는 사용자 지정 모델·저장 폴더가 그 안에 없는지 확인합니다. 이전 모델 경로를 설정에 직접 저장했다면 새 폴더의 `models`로 변경합니다.

## 개발 PC에서 패키지 만들기

```powershell
# EXE 빌드 → 모델·문서·라이선스 포함 → 검증 → ZIP·SHA-256 생성
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\build.ps1
```

고지 원문은 저장소의 `licenses/upstream` 캐시를 사용하여 오프라인으로 수집합니다. 원문을 갱신해야 할 때만 별도 온라인 준비 도구를 실행합니다.

```powershell
.\.venv\Scripts\python.exe .\scripts\prepare_notices.py
```

빌드는 사용자 데이터가 포함될 수 있는 예상 밖의 최상위 파일·폴더, 누락·변조된 모델, 누락된 고지 원문을 발견하면 패키지 생성을 중단합니다. ZIP 생성 후 전체 CRC를 검사하며 `PACKAGE_FILES.json`에 모든 배포 파일의 해시를 기록합니다. 파일 검사는 변조 방지 서명이나 다른 PC 호환성의 보장은 아닙니다.

라이선스 원문과 구성 정보는 [외부 구성 요소 고지](../THIRD_PARTY_NOTICES.md)를 참고하세요. 현재 작업 범위는 개인 PC 간 이동이며, 다른 사람을 대상으로 한 공개 배포 검증을 수행했다는 뜻은 아닙니다.
