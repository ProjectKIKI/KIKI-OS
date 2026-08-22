package main

import (
	"context"
	"flag"
	"fmt"
	"log"
	"net/http"
	"os"
	"strings"
	"time"

	"example.com/aos-pkg/internal/buildsystem"
	"example.com/aos-pkg/internal/controller"
	"example.com/aos-pkg/internal/infraops"
)

func main() {
	host := flag.String("host", "127.0.0.1", "listen host")
	port := flag.Int("port", 8090, "listen port")
	state := flag.String("state", "var/lib/kiki/infraops-state.json", "state JSON path")
	tokenFile := flag.String("token-file", "", "required bearer token file")
	agentTokenFile := flag.String("agent-token-file", "", "node-agent bearer-token file")
	factoryTokenFile := flag.String("factory-token-file", "", "Image Factory bearer-token file")
	buildTokenFile := flag.String("build-token-file", "", "trusted build reporter bearer-token file")
	buildTokenSecret := flag.String("build-token-secret", "kiki-build-reporter", "build namespace Secret containing the build-token key")
	internalInfraOpsURL := flag.String("internal-infraops-url", "http://kiki-infraops.kiki-system.svc.cluster.local:8090", "InfraOps URL reachable from build Pods")
	llamaImage := flag.String("llama-image", "", "digest-pinned llama.cpp image")
	vllmImage := flag.String("vllm-image", "", "digest-pinned vLLM image")
	modelFetcherImage := flag.String("model-fetcher-image", "", "digest-pinned ORAS model fetcher image")
	gitImage := flag.String("git-image", "", "digest-pinned Git client image")
	bosBuilderImage := flag.String("bos-builder-image", "", "digest-pinned BOS builder image")
	allowedGitHosts := flag.String("allowed-git-hosts", "", "comma-separated Git host allowlist")
	allowedSourceHosts := flag.String("allowed-source-hosts", "", "comma-separated BOS recipe source archive host allowlist")
	egressProxyURL := flag.String("build-egress-proxy", "", "HTTP(S) proxy used by source fetch Pods")
	egressProxyCIDR := flag.String("build-egress-proxy-cidr", "", "network CIDR allowed by build NetworkPolicy")
	buildctlImage := flag.String("buildctl-image", "", "digest-pinned buildctl client image")
	supplyChainImage := flag.String("supply-chain-image", "", "digest-pinned SBOM/provenance/signing image")
	modelBuilderImage := flag.String("model-builder-image", "", "digest-pinned model conversion and ORAS publisher image")
	allowedRegistries := flag.String("allowed-registries", "", "comma-separated output registry allowlist")
	buildkitAddress := flag.String("buildkit-address", "", "BuildKit gRPC address")
	buildkitCIDR := flag.String("buildkit-cidr", "", "BuildKit service CIDR allowed by NetworkPolicy")
	buildkitPort := flag.Int("buildkit-port", 1234, "BuildKit service port")
	registryAuthSecret := flag.String("registry-auth-secret", "", "Kubernetes registry credential secret")
	signingSecret := flag.String("signing-secret", "", "Kubernetes artifact signing secret")
	enableController := flag.Bool("enable-kubernetes-controller", false, "reconcile model runtime Pods using the in-cluster API")
	controllerInterval := flag.Duration("controller-interval", 15*time.Second, "model reconciliation interval")
	flag.Parse()
	if *tokenFile == "" {
		log.Fatal("-token-file is required")
	}
	tokenData, err := os.ReadFile(*tokenFile)
	if err != nil {
		log.Fatal(err)
	}
	token := strings.TrimSpace(string(tokenData))
	if token == "" {
		log.Fatal("token file is empty")
	}
	ociConfig := buildsystem.OCIConfig{GitImage: *gitImage, BuildctlImage: *buildctlImage, SupplyChainImage: *supplyChainImage, AllowedGitHosts: splitNonEmpty(*allowedGitHosts), AllowedRegistries: splitNonEmpty(*allowedRegistries), BuildKitAddress: *buildkitAddress, BuildKitCIDR: *buildkitCIDR, BuildKitPort: *buildkitPort, EgressProxyURL: *egressProxyURL, EgressProxyCIDR: *egressProxyCIDR, RegistryAuthSecret: *registryAuthSecret, SigningSecret: *signingSecret, BuildTokenSecret: *buildTokenSecret, InfraOpsURL: *internalInfraOpsURL}
	modelConfig := buildsystem.ModelConfig{GitImage: *gitImage, BuilderImage: *modelBuilderImage, SupplyChainImage: *supplyChainImage, AllowedGitHosts: splitNonEmpty(*allowedGitHosts), AllowedRegistries: splitNonEmpty(*allowedRegistries), EgressProxyURL: *egressProxyURL, EgressProxyCIDR: *egressProxyCIDR, RegistryAuthSecret: *registryAuthSecret, SigningSecret: *signingSecret, BuildTokenSecret: *buildTokenSecret, InfraOpsURL: *internalInfraOpsURL}
	store, err := infraops.NewStore(*state, infraops.RuntimeImages{Llama: *llamaImage, VLLM: *vllmImage, Fetcher: *modelFetcherImage}, buildsystem.Config{GitImage: *gitImage, BOSBuilderImage: *bosBuilderImage, SupplyChainImage: *supplyChainImage, AllowedGitHosts: splitNonEmpty(*allowedGitHosts), AllowedSourceHosts: splitNonEmpty(*allowedSourceHosts), EgressProxyURL: *egressProxyURL, EgressProxyCIDR: *egressProxyCIDR, SigningSecret: *signingSecret, BuildTokenSecret: *buildTokenSecret, InfraOpsURL: *internalInfraOpsURL, OCI: ociConfig, Model: modelConfig})
	if err != nil {
		log.Fatal(err)
	}
	if *enableController {
		pods, err := controller.NewInClusterClient()
		if err != nil {
			log.Fatal(err)
		}
		reconciler := controller.Reconciler{Store: store, Pods: pods, Resources: pods, Builds: pods, Namespace: "kiki-models", Actor: "kiki-controller", Interval: *controllerInterval, OnError: func(err error) { log.Printf("controller reconciliation failed: %v", err) }}
		go func() {
			if err := reconciler.Run(context.Background()); err != nil {
				log.Printf("controller stopped: %v", err)
			}
		}()
	}
	address := fmt.Sprintf("%s:%d", *host, *port)
	principals := []infraops.Principal{{Token: token, Actor: "infraops-admin", Roles: []string{"admin"}}}
	if *agentTokenFile != "" {
		principals = append(principals, infraops.Principal{Token: readToken(*agentTokenFile), Actor: "kiki-agent", Roles: []string{"agent"}})
	}
	if *factoryTokenFile != "" {
		principals = append(principals, infraops.Principal{Token: readToken(*factoryTokenFile), Actor: "image-factory", Roles: []string{"image-factory"}})
	}
	if *buildTokenFile != "" {
		principals = append(principals, infraops.Principal{Token: readToken(*buildTokenFile), Actor: "build-worker", Roles: []string{"build-worker"}})
	}
	handler, err := infraops.NewServerWithPrincipals(store, principals)
	if err != nil {
		log.Fatal(err)
	}
	log.Printf("KIKI InfraOps listening on http://%s", address)
	if err := http.ListenAndServe(address, handler); err != nil {
		log.Fatal(err)
	}
}

func readToken(path string) string {
	data, err := os.ReadFile(path)
	if err != nil {
		log.Fatal(err)
	}
	token := strings.TrimSpace(string(data))
	if token == "" {
		log.Fatalf("token file is empty: %s", path)
	}
	return token
}

func splitNonEmpty(value string) []string {
	var result []string
	for _, item := range strings.Split(value, ",") {
		if trimmed := strings.TrimSpace(item); trimmed != "" {
			result = append(result, trimmed)
		}
	}
	return result
}
