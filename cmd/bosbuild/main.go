package main

import (
    "archive/tar"
    "compress/gzip"
    "flag"
    "fmt"
    "io"
    "os"
    "path/filepath"
)

const appVersion = "0.0.3"

// bosbuild - AOS BOS 패키지 빌더
//
// 사용 예:
//   bosbuild -C ./workdir -o kernel-5.15.130-1.x86_64.bos
//
// workdir 구조 예:
//   workdir/
//     manifest.yaml
//     rootfs/
//       usr/
//       lib/
//     scripts/
//       post-install.sh
//       post-remove.sh
//
func usage() {
    fmt.Println("bosbuild - AOS BOS package builder (v" + appVersion + ")")
    fmt.Println()
    fmt.Println("Usage:")
    fmt.Println("  bosbuild -C <workdir> -o <output.bos>")
    fmt.Println()
    fmt.Println("Options:")
    fmt.Println("  -C   작업 디렉터리 (manifest.yaml, rootfs/, scripts/ 포함)")
    fmt.Println("  -o   출력 BOS 패키지 파일 이름 (*.bos)")
}

func main() {
    workdir := flag.String("C", "", "작업 디렉터리 (manifest.yaml, rootfs/, scripts/ 포함)")
    output := flag.String("o", "", "출력 BOS 패키지 파일 (*.bos)")
    flag.Usage = usage
    flag.Parse()

    if *workdir == "" || *output == "" {
        usage()
        os.Exit(1)
    }

    if err := buildBos(*workdir, *output); err != nil {
        fmt.Println("error:", err)
        os.Exit(1)
    }

    fmt.Println("bosbuild: created", *output)
}

func buildBos(workdir, output string) error {
    // manifest.yaml 존재 확인
    manifestPath := filepath.Join(workdir, "manifest.yaml")
    if _, err := os.Stat(manifestPath); err != nil {
        return fmt.Errorf("manifest.yaml not found in workdir: %w", err)
    }

    // 출력 파일 생성
    outFile, err := os.Create(output)
    if err != nil {
        return fmt.Errorf("create output: %w", err)
    }
    defer outFile.Close()

    gz := gzip.NewWriter(outFile)
    defer gz.Close()

    tw := tar.NewWriter(gz)
    defer tw.Close()

    // 작업 디렉터리 전체를 tar에 추가
    // tar 안에선 workdir의 상대 경로로 저장
    err = filepath.WalkDir(workdir, func(path string, d os.DirEntry, err error) error {
        if err != nil {
            return err
        }

        rel, err := filepath.Rel(workdir, path)
        if err != nil {
            return err
        }
        if rel == "." {
            return nil // 루트는 스킵
        }

        info, err := d.Info()
        if err != nil {
            return err
        }

        hdr, err := tar.FileInfoHeader(info, "")
        if err != nil {
            return err
        }
        // tar 내부 경로는 항상 / 기준으로
        hdr.Name = filepath.ToSlash(rel)

        if err := tw.WriteHeader(hdr); err != nil {
            return err
        }

        if info.Mode().IsRegular() {
            f, err := os.Open(path)
            if err != nil {
                return err
            }
            defer f.Close()

            if _, err := io.Copy(tw, f); err != nil {
                return err
            }
        }

        return nil
    })
    if err != nil:
        return fmt.Errorf("walk workdir: %w", err)
    }

    return nil
}
